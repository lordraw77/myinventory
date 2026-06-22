"""A scanned network / subnet."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Network:
    """A subnet that was (or will be) scanned.

    Used to group hosts into containers in the D2 maps and as section headers
    in the Markdown output.
    """

    cidr: str
    name: Optional[str] = None
    vlan: Optional[int] = None
    description: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.name or self.cidr

    def contains(self, address: str) -> bool:
        """True if ``address`` falls inside this network."""
        try:
            return ipaddress.ip_address(address) in ipaddress.ip_network(
                self.cidr, strict=False
            )
        except ValueError:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cidr": self.cidr,
            "name": self.name,
            "vlan": self.vlan,
            "description": self.description,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Network":
        return cls(
            cidr=data["cidr"],
            name=data.get("name"),
            vlan=data.get("vlan"),
            description=data.get("description"),
            extra=dict(data.get("extra", {})),
        )
