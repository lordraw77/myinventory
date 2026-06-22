"""A network service running on a host."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Service:
    """A single network service observed on a host.

    Produced by service-discovery probes. ``name`` is the logical service
    (``"ssh"``, ``"http"``) while ``product``/``version`` carry the concrete
    software when it can be fingerprinted (``"OpenSSH"`` / ``"9.6p1"``).
    """

    port: int
    protocol: str = "tcp"  # "tcp" | "udp"
    name: str | None = None  # logical service, e.g. "http"
    product: str | None = None  # detected software, e.g. "nginx"
    version: str | None = None
    state: str = "open"  # "open" | "filtered" | "closed"
    banner: str | None = None
    # How this service was detected, e.g. "banner", "nmap", "ssh-probe".
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity within a host: ``proto/port``."""
        return f"{self.protocol}/{self.port}"

    @property
    def label(self) -> str:
        """Human label for diagrams/tables, e.g. ``http (nginx 1.25)``."""
        bits = self.name or self.product or self.key
        if self.product and self.product != self.name:
            ver = f" {self.version}" if self.version else ""
            return f"{bits} ({self.product}{ver})"
        if self.version:
            return f"{bits} {self.version}"
        return bits

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "protocol": self.protocol,
            "name": self.name,
            "product": self.product,
            "version": self.version,
            "state": self.state,
            "banner": self.banner,
            "source": self.source,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Service:
        return cls(
            port=int(data["port"]),
            protocol=data.get("protocol", "tcp"),
            name=data.get("name"),
            product=data.get("product"),
            version=data.get("version"),
            state=data.get("state", "open"),
            banner=data.get("banner"),
            source=data.get("source"),
            extra=dict(data.get("extra", {})),
        )
