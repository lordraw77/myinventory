"""Proxmox VE virtualization backend.

Reference backend for the virtualization layer. It imports ``proxmoxer`` lazily
so the module is safe to import without the ``[virt]`` extra installed; until the
dependency and a live target are present it raises a clear, actionable error.

API used (read-only):
    GET /nodes                                                   -> nodes
    GET /nodes/{node}/qemu                                       -> KVM guests
    GET /nodes/{node}/lxc                                        -> containers
    GET /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces   -> guest IPs
    GET /nodes/{node}/lxc/{vmid}/config                          -> LXC net config
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..models import DiscoverySource, Host, HostRole, PowerState, VirtualMachine
from .base import BackendResult, VirtualizationBackend, register_backend

if TYPE_CHECKING:
    from ..config import HypervisorTarget


@register_backend("proxmox")
class ProxmoxBackend(VirtualizationBackend):
    """Enumerate Proxmox VE nodes, KVM guests and LXC containers."""

    def __init__(self, **options: object) -> None:
        super().__init__(**options)
        self._api: Any = None  # set in connect()

    def connect(self, target: object) -> None:
        try:
            from proxmoxer import ProxmoxAPI  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "proxmox backend requires the 'virt' extra: "
                "pip install 'myinventory[virt]'"
            ) from exc

        self._api = ProxmoxAPI(
            cast("HypervisorTarget", target).host,
            user=getattr(target, "username", None),
            verify_ssl=getattr(target, "verify_tls", True),
            **self._auth_kwargs(target),
        )

    @staticmethod
    def _auth_kwargs(target: object) -> dict:
        """Pick the auth method: API token if given, otherwise password login.

        Proxmox accepts either an API token (``token_name`` + ``secret``) or a
        user password. Tokens are preferred (scoped, revocable); password login
        is supported for setups that don't use tokens.
        """
        user = getattr(target, "username", None)
        token_name = getattr(target, "token_name", None)
        secret = getattr(target, "secret", None)
        password = getattr(target, "password", None)

        if not user:
            raise RuntimeError(
                "proxmox target requires 'username' (e.g. root@pam)"
            )
        if token_name and secret:
            return {"token_name": token_name, "token_value": secret}
        if password:
            return {"password": password}
        raise RuntimeError(
            f"proxmox target {getattr(target, 'host', '?')!r} has no usable "
            "credentials: set either 'token_name'+'secret' or 'password'"
        )

    def collect(self, target: object) -> BackendResult:
        if self._api is None:  # pragma: no cover - guarded by run()
            raise RuntimeError("connect() must be called before collect()")

        result = BackendResult()
        for node in self._api.nodes.get():
            node_name = node["node"]
            hyper = self._hypervisor_host(node, target)
            result.hosts.append(hyper)

            for guest in self._guests(node_name):
                vm = self._to_vm(guest, node_name, hyper.id)
                self._enrich_addresses(vm, node_name, guest, result)
                hyper.hosted_vm_ids.append(vm.id)
                result.vms.append(vm)
        return result

    # --- helpers ----------------------------------------------------------
    def _guests(self, node_name: str) -> list[dict]:
        qemu = self._api.nodes(node_name).qemu.get()
        lxc = self._api.nodes(node_name).lxc.get()
        for g in qemu:
            g["_kind"] = "qemu"
        for g in lxc:
            g["_kind"] = "lxc"
        return [*qemu, *lxc]

    def _enrich_addresses(
        self, vm: VirtualMachine, node_name: str, guest: dict, result: BackendResult
    ) -> None:
        """Best-effort guest IP/MAC lookup. Failures degrade, never abort.

        Running QEMU guests answer the guest agent (if installed); LXC
        containers expose their addresses in the container config.
        """
        kind = guest.get("_kind")
        vmid = guest["vmid"]
        try:
            if kind == "qemu" and vm.power_state == PowerState.RUNNING:
                payload = (
                    self._api.nodes(node_name)
                    .qemu(vmid)
                    .agent("network-get-interfaces")
                    .get()
                )
                ips, macs = _ips_from_agent(payload)
            elif kind == "lxc":
                config = self._api.nodes(node_name).lxc(vmid).config.get()
                ips, macs = _ips_from_lxc_config(config)
            else:
                return
        except Exception as exc:  # noqa: BLE001 - guest agent often absent
            result.errors.append(f"proxmox: {vm.name} ({kind} {vmid}) no IPs: {exc}")
            return
        vm.addresses = ips
        vm.mac_addresses = macs

    @staticmethod
    def _hypervisor_host(node: dict, target: object) -> Host:
        mgmt_ip = cast("HypervisorTarget", target).host
        return Host(
            id=Host.compute_id(address=mgmt_ip, hostname=node["node"]),
            addresses=[mgmt_ip],
            hostname=node["node"],
            role=HostRole.HYPERVISOR,
            os="Proxmox VE",
            sources=[DiscoverySource.VIRTUALIZATION],
        )

    @staticmethod
    def _to_vm(guest: dict, node_name: str, hypervisor_id: str) -> VirtualMachine:
        running = guest.get("status") == "running"
        maxmem = guest.get("maxmem")
        maxdisk = guest.get("maxdisk")
        return VirtualMachine(
            id=f"proxmox:{node_name}:{guest['vmid']}",
            name=guest.get("name", str(guest["vmid"])),
            hypervisor_id=hypervisor_id,
            backend="proxmox",
            power_state=PowerState.RUNNING if running else PowerState.STOPPED,
            vcpus=guest.get("cpus"),
            memory_mb=int(maxmem / 1024 / 1024) if maxmem else None,
            disk_gb=round(maxdisk / 1024**3, 1) if maxdisk else None,
            tags=_split_tags(guest.get("tags")),
            extra={"kind": guest.get("_kind"), "vmid": guest["vmid"]},
        )


# --- pure parsing helpers (unit-tested without a live Proxmox) -------------
def _ips_from_agent(payload: dict) -> tuple[list[str], list[str]]:
    """Extract (ips, macs) from a qemu-guest-agent network-get-interfaces reply.

    Loopback and link-local addresses are dropped; order is preserved and
    de-duplicated so the output diffs cleanly.
    """
    ips: list[str] = []
    macs: list[str] = []
    for iface in payload.get("result", []):
        mac = iface.get("hardware-address")
        if mac and mac not in ("00:00:00:00:00:00",):
            macs.append(mac.lower())
        for entry in iface.get("ip-addresses", []) or []:
            addr = entry.get("ip-address")
            if addr and not _is_local(addr):
                ips.append(addr)
    return _dedupe(ips), _dedupe(macs)


def _ips_from_lxc_config(config: dict) -> tuple[list[str], list[str]]:
    """Extract (ips, macs) from an LXC config's ``netN`` interface entries.

    Each entry looks like ``name=eth0,bridge=vmbr0,hwaddr=AA:..,ip=10.0.0.5/24``.
    DHCP/manual interfaces have no static ``ip=`` and contribute only a MAC.
    """
    ips: list[str] = []
    macs: list[str] = []
    for key, value in config.items():
        if not (key.startswith("net") and key[3:].isdigit()):
            continue
        fields = dict(
            part.split("=", 1) for part in str(value).split(",") if "=" in part
        )
        mac = fields.get("hwaddr")
        if mac:
            macs.append(mac.lower())
        ip = fields.get("ip")
        if ip and ip not in ("dhcp", "manual"):
            addr = ip.split("/", 1)[0]
            if not _is_local(addr):
                ips.append(addr)
    return _dedupe(ips), _dedupe(macs)


def _split_tags(raw: object) -> list[str]:
    """Proxmox stores tags as a semicolon/space-separated string."""
    if not raw:
        return []
    return [t for t in str(raw).replace(";", " ").split() if t]


def _is_local(addr: str) -> bool:
    return (
        addr.startswith("127.")
        or addr == "::1"
        or addr.lower().startswith("fe80")
    )


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
