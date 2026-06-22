"""The aggregate root: everything discovered in one place."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .host import Host
from .network import Network
from .vm import VirtualMachine

SCHEMA_VERSION = 1


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Inventory:
    """All hosts, VMs and networks from one or more scans.

    Collections are keyed by stable ID so merging a fresh scan is an upsert,
    not an append. This is what keeps the JSON/Markdown output diffable.
    """

    hosts: Dict[str, Host] = field(default_factory=dict)
    vms: Dict[str, VirtualMachine] = field(default_factory=dict)
    networks: List[Network] = field(default_factory=list)
    generated_at: str = field(default_factory=_utcnow)
    schema_version: int = SCHEMA_VERSION

    # --- mutation ---------------------------------------------------------
    def upsert_host(self, host: Host) -> Host:
        """Insert ``host`` or merge it into an existing record (last wins)."""
        existing = self.hosts.get(host.id)
        if existing is None:
            host.first_seen = host.first_seen or _utcnow()
            host.last_seen = host.last_seen or host.first_seen
            self.hosts[host.id] = host
            return host
        _merge_host(existing, host)
        return existing

    def upsert_vm(self, vm: VirtualMachine) -> VirtualMachine:
        self.vms[vm.id] = vm
        return vm

    def add_network(self, network: Network) -> None:
        if not any(n.cidr == network.cidr for n in self.networks):
            self.networks.append(network)

    def network_for(self, address: str) -> Optional[Network]:
        for net in self.networks:
            if net.contains(address):
                return net
        return None

    def hosts_in(self, network: Network) -> List[Host]:
        return [
            h
            for h in self.hosts.values()
            if any(network.contains(a) for a in h.addresses)
        ]

    def vms_of(self, hypervisor_id: str) -> List[VirtualMachine]:
        return [v for v in self.vms.values() if v.hypervisor_id == hypervisor_id]

    def merge(self, other: "Inventory") -> None:
        """Merge another inventory (e.g. a prior scan) into this one."""
        for net in other.networks:
            self.add_network(net)
        for host in other.hosts.values():
            self.upsert_host(host)
        for vm in other.vms.values():
            self.upsert_vm(vm)

    # --- serialization ----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "networks": [n.to_dict() for n in self.networks],
            "hosts": [h.to_dict() for h in self.hosts.values()],
            "vms": [v.to_dict() for v in self.vms.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Inventory":
        inv = cls(
            generated_at=data.get("generated_at", _utcnow()),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )
        inv.networks = [Network.from_dict(n) for n in data.get("networks", [])]
        for h in data.get("hosts", []):
            host = Host.from_dict(h)
            inv.hosts[host.id] = host
        for v in data.get("vms", []):
            vm = VirtualMachine.from_dict(v)
            inv.vms[vm.id] = vm
        return inv

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_json(cls, text: str) -> "Inventory":
        return cls.from_dict(json.loads(text))


def _merge_host(target: Host, incoming: Host) -> None:
    """Field-level merge: prefer non-empty incoming values, union lists."""
    target.last_seen = _utcnow()
    target.first_seen = target.first_seen or incoming.first_seen

    for attr in ("hostname", "mac", "os", "hypervisor_id"):
        val = getattr(incoming, attr)
        if val:
            setattr(target, attr, val)

    if incoming.role.value != "unknown":
        target.role = incoming.role

    target.addresses = _union(target.addresses, incoming.addresses)
    target.tags = _union(target.tags, incoming.tags)
    target.hosted_vm_ids = _union(target.hosted_vm_ids, incoming.hosted_vm_ids)
    target.sources = list(dict.fromkeys([*target.sources, *incoming.sources]))

    for svc in incoming.services:
        target.add_service(svc)

    target.extra.update(incoming.extra)


def _union(a: Iterable[str], b: Iterable[str]) -> List[str]:
    """Order-preserving de-duplicated union."""
    return list(dict.fromkeys([*a, *b]))
