"""A virtual machine reported by a hypervisor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PowerState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    UNKNOWN = "unknown"


@dataclass
class VirtualMachine:
    """A guest enumerated from a virtualization backend.

    A VM is linked to its hypervisor via :attr:`hypervisor_id`. If the guest is
    also reachable on the network, correlation links it to a :class:`Host`
    through :attr:`host_id`.
    """

    id: str  # hypervisor-assigned UUID (stable identity)
    name: str
    hypervisor_id: str
    backend: str  # "proxmox" | "vmware" | "libvirt" | ...
    power_state: PowerState = PowerState.UNKNOWN

    vcpus: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[float] = None
    guest_os: Optional[str] = None
    addresses: List[str] = field(default_factory=list)
    mac_addresses: List[str] = field(default_factory=list)

    # Set by correlation when the guest matches a network-discovered host.
    host_id: Optional[str] = None

    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "hypervisor_id": self.hypervisor_id,
            "backend": self.backend,
            "power_state": self.power_state.value,
            "vcpus": self.vcpus,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
            "guest_os": self.guest_os,
            "addresses": self.addresses,
            "mac_addresses": self.mac_addresses,
            "host_id": self.host_id,
            "tags": self.tags,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VirtualMachine":
        return cls(
            id=data["id"],
            name=data["name"],
            hypervisor_id=data["hypervisor_id"],
            backend=data["backend"],
            power_state=PowerState(data.get("power_state", "unknown")),
            vcpus=data.get("vcpus"),
            memory_mb=data.get("memory_mb"),
            disk_gb=data.get("disk_gb"),
            guest_os=data.get("guest_os"),
            addresses=list(data.get("addresses", [])),
            mac_addresses=list(data.get("mac_addresses", [])),
            host_id=data.get("host_id"),
            tags=list(data.get("tags", [])),
            extra=dict(data.get("extra", {})),
        )
