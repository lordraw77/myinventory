"""A discovered host (physical machine, appliance, hypervisor or VM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .service import Service


class HostRole(str, Enum):
    """Best-effort classification of what a host *is*."""

    UNKNOWN = "unknown"
    PHYSICAL = "physical"
    HYPERVISOR = "hypervisor"
    VM = "vm"
    CONTAINER = "container"
    NETWORK = "network"  # switch / router / AP / firewall
    NAS = "nas"
    PRINTER = "printer"


class DiscoverySource(str, Enum):
    """How a host first entered the inventory."""

    ICMP = "icmp"
    ARP = "arp"
    TCP = "tcp"
    NMAP = "nmap"
    VIRTUALIZATION = "virtualization"
    MANUAL = "manual"


@dataclass
class Host:
    """A node in the inventory.

    Identity is derived (see :meth:`compute_id`) so that re-scans map to the
    same record and the output diffs cleanly.
    """

    id: str
    addresses: list[str] = field(default_factory=list)
    hostname: str | None = None
    mac: str | None = None
    role: HostRole = HostRole.UNKNOWN
    os: str | None = None
    services: list[Service] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sources: list[DiscoverySource] = field(default_factory=list)

    # Relationships (populated by virtualization backends + correlation).
    hypervisor_id: str | None = None  # set when this host is a VM
    hosted_vm_ids: list[str] = field(default_factory=list)  # set on a hypervisor

    first_seen: str | None = None  # ISO-8601 UTC
    last_seen: str | None = None  # ISO-8601 UTC
    extra: dict[str, Any] = field(default_factory=dict)

    # --- identity ---------------------------------------------------------
    @property
    def primary_address(self) -> str | None:
        return self.addresses[0] if self.addresses else None

    @staticmethod
    def compute_id(
        mac: str | None = None,
        address: str | None = None,
        hostname: str | None = None,
    ) -> str:
        """Stable identity in priority order: MAC > IP > hostname.

        Prefixed so IDs are self-describing in diagrams/JSON.
        """
        if mac:
            return f"mac:{mac.lower().replace('-', ':')}"
        if address:
            return f"ip:{address}"
        if hostname:
            return f"host:{hostname.lower()}"
        raise ValueError("cannot compute host id without mac, address or hostname")

    # --- helpers ----------------------------------------------------------
    def add_service(self, service: Service) -> None:
        """Add or replace a service, keyed by ``proto/port``."""
        for i, existing in enumerate(self.services):
            if existing.key == service.key:
                self.services[i] = service
                return
        self.services.append(service)

    @property
    def is_hypervisor(self) -> bool:
        return self.role == HostRole.HYPERVISOR or bool(self.hosted_vm_ids)

    # --- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "addresses": self.addresses,
            "hostname": self.hostname,
            "mac": self.mac,
            "role": self.role.value,
            "os": self.os,
            "services": [s.to_dict() for s in self.services],
            "tags": self.tags,
            "sources": [s.value for s in self.sources],
            "hypervisor_id": self.hypervisor_id,
            "hosted_vm_ids": self.hosted_vm_ids,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Host:
        return cls(
            id=data["id"],
            addresses=list(data.get("addresses", [])),
            hostname=data.get("hostname"),
            mac=data.get("mac"),
            role=HostRole(data.get("role", "unknown")),
            os=data.get("os"),
            services=[Service.from_dict(s) for s in data.get("services", [])],
            tags=list(data.get("tags", [])),
            sources=[DiscoverySource(s) for s in data.get("sources", [])],
            hypervisor_id=data.get("hypervisor_id"),
            hosted_vm_ids=list(data.get("hosted_vm_ids", [])),
            first_seen=data.get("first_seen"),
            last_seen=data.get("last_seen"),
            extra=dict(data.get("extra", {})),
        )
