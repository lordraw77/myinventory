"""Proxmox VE virtualization backend.

Reference backend for the virtualization layer. The collection logic below is
the milestone-2 target shape; it imports ``proxmoxer`` lazily so the module is
safe to import without the ``[virt]`` extra installed. Until the dependency and
a live test target are wired up it raises a clear, actionable error.

API used (read-only):
    GET /nodes
    GET /nodes/{node}/qemu          -> KVM guests
    GET /nodes/{node}/lxc           -> containers
    GET /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces  -> guest IPs
"""

from __future__ import annotations

from typing import List

from ..models import DiscoverySource, Host, HostRole, PowerState, VirtualMachine
from .base import BackendResult, VirtualizationBackend, register_backend


@register_backend("proxmox")
class ProxmoxBackend(VirtualizationBackend):
    """Enumerate Proxmox VE nodes, KVM guests and LXC containers."""

    def __init__(self, **options: object) -> None:
        super().__init__(**options)
        self._api = None  # set in connect()

    def connect(self, target: "object") -> None:
        try:
            from proxmoxer import ProxmoxAPI  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "proxmox backend requires the 'virt' extra: "
                "pip install 'myinventory[virt]'"
            ) from exc

        self._api = ProxmoxAPI(
            getattr(target, "host"),
            user=getattr(target, "username", None),
            verify_ssl=getattr(target, "verify_tls", True),
            **self._auth_kwargs(target),
        )

    @staticmethod
    def _auth_kwargs(target: "object") -> dict:
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

    def collect(self, target: "object") -> BackendResult:
        if self._api is None:  # pragma: no cover - guarded by run()
            raise RuntimeError("connect() must be called before collect()")

        result = BackendResult()
        for node in self._api.nodes.get():
            node_name = node["node"]
            hyper = self._hypervisor_host(node, target)
            result.hosts.append(hyper)

            for guest in self._guests(node_name):
                vm = self._to_vm(guest, node_name, hyper.id)
                hyper.hosted_vm_ids.append(vm.id)
                result.vms.append(vm)
        return result

    # --- helpers ----------------------------------------------------------
    def _guests(self, node_name: str) -> List[dict]:
        qemu = self._api.nodes(node_name).qemu.get()
        lxc = self._api.nodes(node_name).lxc.get()
        for g in qemu:
            g["_kind"] = "qemu"
        for g in lxc:
            g["_kind"] = "lxc"
        return [*qemu, *lxc]

    @staticmethod
    def _hypervisor_host(node: dict, target: "object") -> Host:
        mgmt_ip = getattr(target, "host")
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
        return VirtualMachine(
            id=f"proxmox:{node_name}:{guest['vmid']}",
            name=guest.get("name", str(guest["vmid"])),
            hypervisor_id=hypervisor_id,
            backend="proxmox",
            power_state=PowerState.RUNNING if running else PowerState.STOPPED,
            vcpus=guest.get("cpus"),
            memory_mb=int(guest["maxmem"] / 1024 / 1024) if guest.get("maxmem") else None,
            disk_gb=round(guest["maxdisk"] / 1024**3, 1) if guest.get("maxdisk") else None,
            extra={"kind": guest.get("_kind"), "vmid": guest["vmid"]},
        )
