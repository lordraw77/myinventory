"""Software inventory records produced by deep (SSH) inspection.

These hang off a :class:`~myinventory.models.host.Host`: a host carries the
packages installed on it, the notable processes running on it and the containers
its runtime hosts. They contain no I/O — the SSH inspectors build them, storage
persists them and the renderers display them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Package:
    """An installed software package, normalized across package managers."""

    name: str
    version: str | None = None
    manager: str = "unknown"  # dpkg | rpm | snap | flatpak | ...

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "manager": self.manager}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Package:
        return cls(
            name=data["name"],
            version=data.get("version"),
            manager=data.get("manager", "unknown"),
        )


@dataclass
class Process:
    """A running process worth recording (a top consumer or a port owner)."""

    pid: int
    name: str
    user: str | None = None
    cpu_percent: float | None = None
    rss_kb: int | None = None
    command: str | None = None
    #: Ports this process listens on (filled by socket↔process correlation).
    listening_ports: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "user": self.user,
            "cpu_percent": self.cpu_percent,
            "rss_kb": self.rss_kb,
            "command": self.command,
            "listening_ports": self.listening_ports,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Process:
        return cls(
            pid=int(data["pid"]),
            name=data["name"],
            user=data.get("user"),
            cpu_percent=data.get("cpu_percent"),
            rss_kb=data.get("rss_kb"),
            command=data.get("command"),
            listening_ports=list(data.get("listening_ports", [])),
        )


@dataclass
class Container:
    """A container reported by a host's runtime (Docker / Podman / containerd)."""

    id: str
    name: str
    image: str | None = None
    state: str | None = None  # running | exited | created | paused | ...
    runtime: str = "docker"  # docker | podman | containerd
    ports: list[str] = field(default_factory=list)  # "0.0.0.0:8080->80/tcp"
    mounts: list[str] = field(default_factory=list)
    restart_policy: str | None = None
    compose_project: str | None = None
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return (self.state or "").lower() == "running"

    @property
    def published_ports(self) -> list[int]:
        """Host-side TCP ports this container publishes (for service mapping)."""
        out: list[int] = []
        for spec in self.ports:
            # Shapes: "0.0.0.0:8080->80/tcp", ":::8080->80/tcp", "80/tcp".
            host_side = spec.split("->", 1)[0]
            if ":" not in host_side:
                continue
            port = host_side.rsplit(":", 1)[-1]
            if port.isdigit():
                out.append(int(port))
        return list(dict.fromkeys(out))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "state": self.state,
            "runtime": self.runtime,
            "ports": self.ports,
            "mounts": self.mounts,
            "restart_policy": self.restart_policy,
            "compose_project": self.compose_project,
            "labels": self.labels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Container:
        return cls(
            id=data["id"],
            name=data["name"],
            image=data.get("image"),
            state=data.get("state"),
            runtime=data.get("runtime", "docker"),
            ports=list(data.get("ports", [])),
            mounts=list(data.get("mounts", [])),
            restart_policy=data.get("restart_policy"),
            compose_project=data.get("compose_project"),
            labels=dict(data.get("labels", {})),
        )
