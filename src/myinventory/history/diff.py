"""Compute a structured diff between two inventories.

A *diff* answers "what changed between scan A and scan B": which hosts appeared,
which vanished, and — for hosts present in both — which fields drifted (role, OS,
hostname, services, …). The same treatment is applied to virtual machines.

The result is a pure data object (:class:`InventoryDiff`); rendering it to
Markdown lives in :mod:`.changelog` and the human/JSON summaries live in the CLI.
This module does no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Host, Inventory, Service, VirtualMachine


@dataclass
class FieldChange:
    """A single scalar field that moved from ``before`` to ``after``."""

    field: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "before": self.before, "after": self.after}


@dataclass
class HostChange:
    """A host present in both scans whose details drifted."""

    id: str
    label: str
    fields: list[FieldChange] = field(default_factory=list)
    services_added: list[str] = field(default_factory=list)
    services_removed: list[str] = field(default_factory=list)
    services_changed: list[FieldChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.fields
            or self.services_added
            or self.services_removed
            or self.services_changed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "fields": [c.to_dict() for c in self.fields],
            "services_added": self.services_added,
            "services_removed": self.services_removed,
            "services_changed": [c.to_dict() for c in self.services_changed],
        }


@dataclass
class VmChange:
    """A VM present in both scans whose details drifted."""

    id: str
    name: str
    fields: list[FieldChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.fields

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fields": [c.to_dict() for c in self.fields],
        }


@dataclass
class InventoryDiff:
    """The complete set of differences between two inventories."""

    old_generated_at: str | None = None
    new_generated_at: str | None = None

    hosts_added: list[Host] = field(default_factory=list)
    hosts_removed: list[Host] = field(default_factory=list)
    hosts_changed: list[HostChange] = field(default_factory=list)

    vms_added: list[VirtualMachine] = field(default_factory=list)
    vms_removed: list[VirtualMachine] = field(default_factory=list)
    vms_changed: list[VmChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.hosts_added
            or self.hosts_removed
            or self.hosts_changed
            or self.vms_added
            or self.vms_removed
            or self.vms_changed
        )

    def summary(self) -> str:
        """One-line tally, e.g. ``+2 hosts, -1 host, 3 changed; +1 VM``."""
        parts: list[str] = []
        if self.hosts_added:
            parts.append(f"+{len(self.hosts_added)} hosts")
        if self.hosts_removed:
            parts.append(f"-{len(self.hosts_removed)} hosts")
        if self.hosts_changed:
            parts.append(f"~{len(self.hosts_changed)} hosts")
        if self.vms_added:
            parts.append(f"+{len(self.vms_added)} VMs")
        if self.vms_removed:
            parts.append(f"-{len(self.vms_removed)} VMs")
        if self.vms_changed:
            parts.append(f"~{len(self.vms_changed)} VMs")
        return ", ".join(parts) if parts else "no changes"

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_generated_at": self.old_generated_at,
            "new_generated_at": self.new_generated_at,
            "hosts_added": [_host_brief(h) for h in self.hosts_added],
            "hosts_removed": [_host_brief(h) for h in self.hosts_removed],
            "hosts_changed": [c.to_dict() for c in self.hosts_changed],
            "vms_added": [_vm_brief(v) for v in self.vms_added],
            "vms_removed": [_vm_brief(v) for v in self.vms_removed],
            "vms_changed": [c.to_dict() for c in self.vms_changed],
        }


#: Host fields compared for drift, with a friendly label for each.
_HOST_FIELDS = (
    ("hostname", "hostname"),
    ("mac", "mac"),
    ("os", "os"),
    ("hypervisor_id", "hypervisor"),
)
#: VM fields compared for drift.
_VM_FIELDS = (
    ("power_state", "power state"),
    ("vcpus", "vcpus"),
    ("memory_mb", "memory (MB)"),
    ("guest_os", "guest OS"),
    ("hypervisor_id", "hypervisor"),
)


def diff_inventories(old: Inventory, new: Inventory) -> InventoryDiff:
    """Return the differences turning ``old`` into ``new``."""
    result = InventoryDiff(
        old_generated_at=old.generated_at,
        new_generated_at=new.generated_at,
    )

    old_ids = set(old.hosts)
    new_ids = set(new.hosts)
    result.hosts_added = [new.hosts[i] for i in new_ids - old_ids]
    result.hosts_removed = [old.hosts[i] for i in old_ids - new_ids]
    for hid in old_ids & new_ids:
        change = _diff_host(old.hosts[hid], new.hosts[hid])
        if not change.is_empty:
            result.hosts_changed.append(change)

    old_vms = set(old.vms)
    new_vms = set(new.vms)
    result.vms_added = [new.vms[i] for i in new_vms - old_vms]
    result.vms_removed = [old.vms[i] for i in old_vms - new_vms]
    for vid in old_vms & new_vms:
        vm_change = _diff_vm(old.vms[vid], new.vms[vid])
        if not vm_change.is_empty:
            result.vms_changed.append(vm_change)

    # Deterministic ordering keeps the rendered changelog diff-stable.
    result.hosts_added.sort(key=_host_sort_key)
    result.hosts_removed.sort(key=_host_sort_key)
    result.hosts_changed.sort(key=lambda c: c.label)
    result.vms_added.sort(key=lambda v: v.name)
    result.vms_removed.sort(key=lambda v: v.name)
    result.vms_changed.sort(key=lambda c: c.name)
    return result


def _diff_host(old: Host, new: Host) -> HostChange:
    label = new.hostname or new.primary_address or new.id
    change = HostChange(id=new.id, label=label)

    if old.role.value != new.role.value:
        change.fields.append(FieldChange("role", old.role.value, new.role.value))
    for attr, name in _HOST_FIELDS:
        before = getattr(old, attr)
        after = getattr(new, attr)
        if before != after:
            change.fields.append(FieldChange(name, before, after))
    if sorted(old.addresses) != sorted(new.addresses):
        change.fields.append(
            FieldChange("addresses", ", ".join(old.addresses), ", ".join(new.addresses))
        )

    old_svc = {s.key: s for s in old.services}
    new_svc = {s.key: s for s in new.services}
    change.services_added = sorted(
        new_svc[k].label for k in new_svc.keys() - old_svc.keys()
    )
    change.services_removed = sorted(
        old_svc[k].label for k in old_svc.keys() - new_svc.keys()
    )
    for key in old_svc.keys() & new_svc.keys():
        label_change = _diff_service(old_svc[key], new_svc[key])
        if label_change is not None:
            change.services_changed.append(label_change)
    change.services_changed.sort(key=lambda c: c.field)
    return change


def _diff_service(old: Service, new: Service) -> FieldChange | None:
    """Report a service whose identifying label drifted (e.g. version bump)."""
    if old.label != new.label:
        return FieldChange(old.key, old.label, new.label)
    return None


def _diff_vm(old: VirtualMachine, new: VirtualMachine) -> VmChange:
    change = VmChange(id=new.id, name=new.name)
    for attr, name in _VM_FIELDS:
        before = getattr(old, attr)
        after = getattr(new, attr)
        before_val = before.value if hasattr(before, "value") else before
        after_val = after.value if hasattr(after, "value") else after
        if before_val != after_val:
            change.fields.append(FieldChange(name, before_val, after_val))
    if sorted(old.addresses) != sorted(new.addresses):
        change.fields.append(
            FieldChange("addresses", ", ".join(old.addresses), ", ".join(new.addresses))
        )
    return change


def _host_sort_key(host: Host) -> str:
    return host.primary_address or host.hostname or host.id


def _host_brief(host: Host) -> dict[str, Any]:
    return {
        "id": host.id,
        "label": host.hostname or host.primary_address or host.id,
        "address": host.primary_address,
        "role": host.role.value,
    }


def _vm_brief(vm: VirtualMachine) -> dict[str, Any]:
    return {"id": vm.id, "name": vm.name, "hypervisor_id": vm.hypervisor_id}
