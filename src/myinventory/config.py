"""Configuration: YAML file -> typed objects.

Credentials are never written inline. A ``CredentialRef`` names an environment
variable (``env:PROXMOX_TOKEN``) or a secret file; the value is resolved at run
time. See ``docs/configuration.md`` and ``docs/security.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ConfigError(ValueError):
    """Raised when the config file is malformed or references a missing secret."""


@dataclass
class NetworkTarget:
    """A subnet to scan and the discovery backends to use on it."""

    cidr: str
    name: Optional[str] = None
    vlan: Optional[int] = None
    discovery: List[str] = field(default_factory=lambda: ["tcp"])
    probe_ports: Optional[List[int]] = None
    timeout: float = 0.5
    workers: int = 128


@dataclass
class HypervisorTarget:
    """A hypervisor / cluster management endpoint to enumerate VMs from."""

    type: str  # registry key: "proxmox" | "vmware" | "libvirt"
    host: str
    username: Optional[str] = None
    password: Optional[str] = None
    token_name: Optional[str] = None
    secret: Optional[str] = None
    verify_tls: bool = True
    name: Optional[str] = None


@dataclass
class LinuxSshTarget:
    """A Linux host (or set of hosts) to inspect over SSH.

    Authentication is flexible: an SSH key (``key_file``) and/or a login
    ``password``. When a command needs elevated privileges, ``sudo_password``
    is fed to ``sudo -S``; leave it unset for passwordless sudo or to stay
    strictly unprivileged. All three secret fields accept ``env:``/``file:``
    references and are resolved at load time.
    """

    host: str
    username: str = "root"
    password: Optional[str] = None
    key_file: Optional[str] = None
    sudo: bool = False
    sudo_password: Optional[str] = None
    port: int = 22
    name: Optional[str] = None


@dataclass
class AppConfig:
    """Top-level configuration."""

    networks: List[NetworkTarget] = field(default_factory=list)
    hypervisors: List[HypervisorTarget] = field(default_factory=list)
    linux_ssh: List[LinuxSshTarget] = field(default_factory=list)
    service_probes: List[str] = field(default_factory=lambda: ["banner"])
    workers: int = 64
    output_dir: str = "./out"

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        networks = [_network(n) for n in data.get("networks", [])]
        hypervisors = [_hypervisor(h) for h in data.get("hypervisors", [])]
        linux_ssh = [_linux_ssh(s) for s in data.get("linux_ssh", [])]
        return cls(
            networks=networks,
            hypervisors=hypervisors,
            linux_ssh=linux_ssh,
            service_probes=data.get("service_probes", ["banner"]),
            workers=int(data.get("workers", 64)),
            output_dir=data.get("output_dir", "./out"),
        )


def _network(data: Dict[str, Any]) -> NetworkTarget:
    if "cidr" not in data:
        raise ConfigError("each network entry requires a 'cidr'")
    return NetworkTarget(
        cidr=data["cidr"],
        name=data.get("name"),
        vlan=data.get("vlan"),
        discovery=list(data.get("discovery", ["tcp"])),
        probe_ports=data.get("probe_ports"),
        timeout=float(data.get("timeout", 0.5)),
        workers=int(data.get("workers", 128)),
    )


def _hypervisor(data: Dict[str, Any]) -> HypervisorTarget:
    for required in ("type", "host"):
        if required not in data:
            raise ConfigError(f"each hypervisor entry requires '{required}'")
    return HypervisorTarget(
        type=data["type"],
        host=data["host"],
        username=data.get("username"),
        password=_resolve_secret(data.get("password")),
        token_name=data.get("token_name"),
        secret=_resolve_secret(data.get("secret")),
        verify_tls=bool(data.get("verify_tls", True)),
        name=data.get("name"),
    )


def _linux_ssh(data: Dict[str, Any]) -> LinuxSshTarget:
    if "host" not in data:
        raise ConfigError("each linux_ssh entry requires a 'host'")
    sudo_password = _resolve_secret(data.get("sudo_password"))
    return LinuxSshTarget(
        host=data["host"],
        username=data.get("username", "root"),
        password=_resolve_secret(data.get("password")),
        key_file=data.get("key_file"),
        # sudo is implied when a sudo password is supplied.
        sudo=bool(data.get("sudo", sudo_password is not None)),
        sudo_password=sudo_password,
        port=int(data.get("port", 22)),
        name=data.get("name"),
    )


def _resolve_secret(ref: Optional[str]) -> Optional[str]:
    """Resolve a secret reference.

    * ``env:NAME``   -> value of environment variable ``NAME``
    * ``file:/path`` -> contents of the file (trimmed)
    * anything else  -> returned as-is (discouraged; emits no error here)
    """
    if not ref:
        return None
    if ref.startswith("env:"):
        name = ref[4:]
        val = os.environ.get(name)
        if val is None:
            raise ConfigError(f"environment variable {name!r} referenced but not set")
        return val
    if ref.startswith("file:"):
        p = Path(ref[5:])
        if not p.exists():
            raise ConfigError(f"secret file not found: {p}")
        return p.read_text().strip()
    return ref
