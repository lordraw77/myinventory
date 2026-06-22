"""libvirt (KVM/QEMU) virtualization backend.

Connects to a libvirt daemon — locally (``qemu:///system``) or remotely over SSH
/ TLS (``qemu+ssh://root@host/system``) — and enumerates its domains. The
``libvirt`` Python binding is imported lazily so the module stays importable
without the ``[virt]`` extra.

Guest IP/MAC discovery uses the qemu-guest-agent when present
(``virDomain.interfaceAddresses``); it degrades to MAC-only (or nothing) when the
agent is absent, never aborting the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..models import DiscoverySource, Host, HostRole, PowerState, VirtualMachine
from .base import BackendResult, VirtualizationBackend, register_backend

if TYPE_CHECKING:
    from ..config import HypervisorTarget

# libvirt domain state codes (see VIR_DOMAIN_* in libvirt-domain.h). Mapped here
# so the parsing helper needs no live binding to be unit-tested.
_STATE_BY_CODE = {
    0: PowerState.UNKNOWN,   # NOSTATE
    1: PowerState.RUNNING,   # RUNNING
    2: PowerState.RUNNING,   # BLOCKED (running but not schedulable)
    3: PowerState.PAUSED,    # PAUSED
    4: PowerState.RUNNING,   # SHUTDOWN (in progress)
    5: PowerState.STOPPED,   # SHUTOFF
    6: PowerState.STOPPED,   # CRASHED
    7: PowerState.PAUSED,    # PMSUSPENDED
}

# virDomain.interfaceAddresses source: query the in-guest agent.
_SRC_AGENT = 1
# IP address types in the interfaceAddresses reply.
_IP_TYPE_IPV4 = 0


@register_backend("libvirt")
class LibvirtBackend(VirtualizationBackend):
    """Enumerate libvirt domains and the host running them."""

    def __init__(self, **options: object) -> None:
        super().__init__(**options)
        self._conn: Any = None  # set in connect()
        self._lib: Any = None

    def connect(self, target: object) -> None:
        try:
            import libvirt  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "libvirt backend requires the 'virt' extra: "
                "pip install 'myinventory[virt]'"
            ) from exc

        self._lib = libvirt
        uri = getattr(target, "host", None)
        if not uri:
            raise RuntimeError("libvirt target requires 'host' (a libvirt URI)")
        # Read-only is enough for inventory and avoids needing write privileges.
        self._conn = libvirt.openReadOnly(uri)
        if self._conn is None:  # pragma: no cover - libvirt returns None on failure
            raise RuntimeError(f"libvirt could not open connection to {uri!r}")

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            self._conn = None

    def collect(self, target: object) -> BackendResult:
        if self._conn is None:  # pragma: no cover - guarded by run()
            raise RuntimeError("connect() must be called before collect()")

        result = BackendResult()
        hyper = self._hypervisor_host(target)
        result.hosts.append(hyper)

        for dom in self._conn.listAllDomains():
            vm = self._domain_to_vm(dom, hyper.id, result)
            hyper.hosted_vm_ids.append(vm.id)
            result.vms.append(vm)
        return result

    # --- helpers ----------------------------------------------------------
    def _hypervisor_host(self, target: object) -> Host:
        uri = getattr(target, "host", "")
        hostname = self._safe_hostname()
        mgmt = _host_from_uri(uri) or hostname or ""
        is_ip = _looks_like_ip(mgmt)
        return Host(
            id=Host.compute_id(
                address=mgmt if is_ip else None, hostname=hostname or mgmt
            ),
            addresses=[mgmt] if is_ip else [],
            hostname=hostname,
            role=HostRole.HYPERVISOR,
            os="libvirt (KVM/QEMU)",
            sources=[DiscoverySource.VIRTUALIZATION],
        )

    def _safe_hostname(self) -> str | None:
        try:
            return self._conn.getHostname()
        except Exception:  # noqa: BLE001 - non-fatal
            return None

    def _domain_to_vm(
        self, dom: Any, hypervisor_id: str, result: BackendResult
    ) -> VirtualMachine:
        state_code, _max_mem_kib, mem_kib, vcpus, _cpu = dom.info()
        vm = VirtualMachine(
            id=f"libvirt:{dom.UUIDString()}",
            name=dom.name(),
            hypervisor_id=hypervisor_id,
            backend="libvirt",
            power_state=_power_state_from_code(state_code),
            vcpus=vcpus or None,
            memory_mb=int(mem_kib / 1024) if mem_kib else None,
            extra={"uuid": dom.UUIDString()},
        )
        self._enrich_addresses(dom, vm, result)
        return vm

    def _enrich_addresses(
        self, dom: Any, vm: VirtualMachine, result: BackendResult
    ) -> None:
        if vm.power_state != PowerState.RUNNING:
            return
        try:
            ifaces = dom.interfaceAddresses(_SRC_AGENT, 0)
        except Exception as exc:  # noqa: BLE001 - agent commonly absent
            result.errors.append(f"libvirt: {vm.name} no guest agent: {exc}")
            return
        ips, macs = _ips_from_interface_addresses(ifaces)
        vm.addresses = ips
        vm.mac_addresses = macs


# --- pure parsing helpers (unit-tested without a live libvirt) -------------
def _power_state_from_code(code: int) -> PowerState:
    return _STATE_BY_CODE.get(code, PowerState.UNKNOWN)


def _ips_from_interface_addresses(ifaces: dict) -> tuple[list[str], list[str]]:
    """Extract (ips, macs) from ``virDomain.interfaceAddresses`` output.

    Shape: ``{ifname: {"hwaddr": "...", "addrs": [{"addr": "...", "type": 0}]}}``.
    Loopback / link-local addresses are dropped.
    """
    ips: list[str] = []
    macs: list[str] = []
    for iface in (ifaces or {}).values():
        if iface.get("name") == "lo":
            continue
        mac = iface.get("hwaddr")
        if mac and mac != "00:00:00:00:00:00":
            macs.append(mac.lower())
        for entry in iface.get("addrs") or []:
            addr = entry.get("addr")
            if addr and not _is_local(addr):
                ips.append(addr)
    return _dedupe(ips), _dedupe(macs)


def _host_from_uri(uri: str) -> str | None:
    """Pull the remote host out of a libvirt URI; ``None`` for local URIs."""
    try:
        return urlparse(uri).hostname
    except Exception:  # noqa: BLE001 - defensive
        return None


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
