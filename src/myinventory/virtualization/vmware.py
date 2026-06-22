"""VMware vSphere / ESXi virtualization backend.

Connects to a vCenter Server or a standalone ESXi host with ``pyvmomi`` and
enumerates the ESXi hosts and their virtual machines. The SDK is imported lazily
so the module stays importable without the ``[virt]`` extra.

Read-only: a ``Read-Only`` vSphere role is sufficient. Guest IP/MAC come from
VMware Tools (``vm.guest.net``); they are absent when Tools is not running, which
degrades gracefully to no addresses rather than failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..models import DiscoverySource, Host, HostRole, PowerState, VirtualMachine
from .base import BackendResult, VirtualizationBackend, register_backend

if TYPE_CHECKING:
    from ..config import HypervisorTarget

_POWER_BY_STATE = {
    "poweredOn": PowerState.RUNNING,
    "poweredOff": PowerState.STOPPED,
    "suspended": PowerState.PAUSED,
}


@register_backend("vmware")
class VMwareBackend(VirtualizationBackend):
    """Enumerate ESXi hosts and their VMs via vCenter or standalone ESXi."""

    def __init__(self, **options: object) -> None:
        super().__init__(**options)
        self._si: Any = None  # service instance, set in connect()

    def connect(self, target: object) -> None:
        try:
            from pyVim.connect import SmartConnect  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "vmware backend requires the 'virt' extra: "
                "pip install 'myinventory[virt]'"
            ) from exc

        tgt = cast("HypervisorTarget", target)
        if not tgt.username or not tgt.password:
            raise RuntimeError(
                f"vmware target {tgt.host!r} requires 'username' and 'password'"
            )
        self._si = SmartConnect(
            host=tgt.host,
            user=tgt.username,
            pwd=tgt.password,
            disableSslCertValidation=not getattr(tgt, "verify_tls", True),
        )

    def close(self) -> None:
        if self._si is not None:
            try:
                from pyVim.connect import Disconnect

                Disconnect(self._si)
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            self._si = None

    def collect(self, target: object) -> BackendResult:
        if self._si is None:  # pragma: no cover - guarded by run()
            raise RuntimeError("connect() must be called before collect()")
        from pyVmomi import vim  # type: ignore

        content = self._si.RetrieveContent()
        result = BackendResult()

        host_index: dict[str, Host] = {}
        for host_system in _view(content, vim.HostSystem):
            record = self._host_to_record(host_system)
            host_index[host_system._moId] = record
            result.hosts.append(record)

        for vm in _view(content, vim.VirtualMachine):
            host_moid = getattr(getattr(vm.runtime, "host", None), "_moId", None)
            hyper = host_index.get(host_moid) if host_moid else None
            hyper_id = hyper.id if hyper is not None else f"vmware:{target_host(target)}"
            vm_record = self._vm_to_record(vm, hyper_id)
            if hyper is not None:
                hyper.hosted_vm_ids.append(vm_record.id)
            result.vms.append(vm_record)
        return result

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _host_to_record(host_system: Any) -> Host:
        name = host_system.name
        product = getattr(getattr(host_system.summary.config, "product", None), "fullName", None)
        return Host(
            id=Host.compute_id(
                address=name if _looks_like_ip(name) else None, hostname=name
            ),
            addresses=[name] if _looks_like_ip(name) else [],
            hostname=name,
            role=HostRole.HYPERVISOR,
            os=product or "VMware ESXi",
            sources=[DiscoverySource.VIRTUALIZATION],
        )

    @staticmethod
    def _vm_to_record(vm: Any, hypervisor_id: str) -> VirtualMachine:
        summary = vm.summary
        config = summary.config
        ips, macs = _ips_from_guest_net(getattr(vm.guest, "net", None))
        pool = getattr(getattr(vm, "resourcePool", None), "name", None)
        record = VirtualMachine(
            id=f"vmware:{config.instanceUuid or config.uuid}",
            name=config.name,
            hypervisor_id=hypervisor_id,
            backend="vmware",
            power_state=_power_state_from_state(summary.runtime.powerState),
            vcpus=config.numCpu,
            memory_mb=config.memorySizeMB,
            guest_os=config.guestFullName,
            addresses=ips,
            mac_addresses=macs,
            extra={"resource_pool": pool} if pool else {},
        )
        return record


# --- pure parsing helpers (unit-tested without a live vCenter) -------------
def _power_state_from_state(state: str) -> PowerState:
    return _POWER_BY_STATE.get(str(state), PowerState.UNKNOWN)


def _ips_from_guest_net(nics: Any) -> tuple[list[str], list[str]]:
    """Extract (ips, macs) from ``vm.guest.net`` (a list of GuestNicInfo).

    Each NIC exposes ``macAddress`` and an ``ipAddress`` list of strings.
    Loopback / link-local addresses are dropped.
    """
    ips: list[str] = []
    macs: list[str] = []
    for nic in nics or []:
        mac = getattr(nic, "macAddress", None)
        if mac:
            macs.append(mac.lower())
        for addr in getattr(nic, "ipAddress", None) or []:
            if addr and not _is_local(addr):
                ips.append(addr)
    return _dedupe(ips), _dedupe(macs)


def target_host(target: object) -> str:
    return getattr(target, "host", "unknown")


def _looks_like_ip(value: str | None) -> bool:
    if not value:
        return False
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _is_local(addr: str) -> bool:
    return (
        addr.startswith("127.")
        or addr == "::1"
        or addr.lower().startswith("fe80")
    )


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _view(content: Any, vim_type: Any) -> list[Any]:
    """Return all managed objects of ``vim_type`` under the root folder."""
    view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim_type], True
    )
    try:
        return list(view.view)
    finally:
        try:
            view.Destroy()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
