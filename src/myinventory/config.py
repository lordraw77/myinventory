"""Configuration: YAML file -> typed objects.

Credentials are never written inline. A ``CredentialRef`` names an environment
variable (``env:PROXMOX_TOKEN``) or a secret file; the value is resolved at run
time. See ``docs/configuration.md`` and ``docs/security.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the config file is malformed or references a missing secret."""


@dataclass
class NetworkTarget:
    """A subnet to scan and the discovery backends to use on it."""

    cidr: str
    name: str | None = None
    vlan: int | None = None
    discovery: list[str] = field(default_factory=lambda: ["tcp"])
    probe_ports: list[int] | None = None
    timeout: float = 0.5
    workers: int = 128
    #: Max probes per second across the sweep (0 = unlimited).
    rate_limit: float = 0.0
    #: Overall wall-clock budget for one network's sweep, in seconds (None = no cap).
    target_timeout: float | None = None


@dataclass
class HypervisorTarget:
    """A hypervisor / cluster management endpoint to enumerate VMs from."""

    type: str  # registry key: "proxmox" | "vmware" | "libvirt"
    host: str
    username: str | None = None
    password: str | None = None
    token_name: str | None = None
    secret: str | None = None
    verify_tls: bool = True
    name: str | None = None


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
    password: str | None = None
    key_file: str | None = None
    sudo: bool = False
    sudo_password: str | None = None
    port: int = 22
    name: str | None = None
    #: Reject hosts missing from known_hosts. Set ``false`` to auto-accept new
    #: host keys (convenient for a homelab, weaker against MITM).
    strict_host_key: bool = True


@dataclass
class SnmpConfig:
    """SNMP polling settings for the enrichment stage.

    Disabled by default: it needs the ``snmp`` extra and a community string.
    ``community`` accepts an ``env:``/``file:`` reference like any other secret.
    """

    enabled: bool = False
    community: str = "public"
    version: str = "2c"  # "1" | "2c"
    port: int = 161
    timeout: float = 1.0
    retries: int = 1


@dataclass
class ClassificationRule:
    """A declarative user rule: when every set condition matches, apply outcome.

    Conditions (all that are non-empty must hold): ``ports`` (any open),
    ``services`` (any service name present), ``os_contains``, ``vendor_contains``
    and ``hostname_regex``. Outcome assigns ``role`` and/or appends ``tags``.
    User rules are explicit intent and override heuristic classification.
    """

    role: str | None = None
    tags: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    os_contains: str | None = None
    vendor_contains: str | None = None
    hostname_regex: str | None = None


@dataclass
class EnrichmentConfig:
    """Milestone-4 enrichment toggles.

    The cheap, dependency-free passes (reverse DNS, OS fingerprint heuristics and
    classification) default on; SNMP is opt-in.
    """

    reverse_dns: bool = True
    #: Paths to DHCP lease files (dnsmasq or ISC ``dhcpd.leases``) to read
    #: client-supplied hostnames from.
    dhcp_leases: list[str] = field(default_factory=list)
    os_fingerprint: bool = True
    classify: bool = True
    snmp: SnmpConfig = field(default_factory=SnmpConfig)
    rules: list[ClassificationRule] = field(default_factory=list)


@dataclass
class WebhookTarget:
    """An HTTP endpoint to POST a change summary to.

    ``format`` is ``json`` (a generic ``{title, summary, body, diff}`` payload)
    or ``slack`` (``{"text": ...}`` for Slack/Mattermost incoming webhooks).
    """

    url: str
    format: str = "json"  # "json" | "slack"
    timeout: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class EmailTarget:
    """SMTP settings for emailing a change summary.

    ``password`` accepts an ``env:``/``file:`` reference like any other secret.
    Auth is attempted only when ``username`` is set; ``use_tls`` turns on
    STARTTLS.
    """

    host: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    port: int = 25
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    subject_prefix: str = ""


@dataclass
class NotificationsConfig:
    """Milestone-6 change notifications. Opt-in and best-effort.

    When ``enabled`` and (by default) the scan actually changed something, a
    summary is dispatched to every configured webhook and the email target. A
    failing channel is recorded as a scan error, never fatal.
    """

    enabled: bool = False
    #: Only notify when the diff against the previous scan is non-empty.
    on_change_only: bool = True
    webhooks: list[WebhookTarget] = field(default_factory=list)
    email: EmailTarget | None = None


@dataclass
class StorageConfig:
    """Where and how the inventory is persisted (Milestone 5).

    ``backend`` selects ``json`` (an ``inventory.json`` plus a ``history/``
    directory) or ``sqlite`` (a single ``inventory.db``). ``keep_history``
    records a per-scan snapshot for change tracking; ``stale_after_scans`` is the
    number of consecutive scans a host may be missing before it is flagged stale.
    """

    backend: str = "json"  # "json" | "sqlite"
    keep_history: bool = True
    stale_after_scans: int = 3


@dataclass
class AppConfig:
    """Top-level configuration."""

    networks: list[NetworkTarget] = field(default_factory=list)
    hypervisors: list[HypervisorTarget] = field(default_factory=list)
    linux_ssh: list[LinuxSshTarget] = field(default_factory=list)
    service_probes: list[str] = field(default_factory=lambda: ["banner"])
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    workers: int = 64
    output_dir: str = "./out"
    #: Label for the scanned estate (a site/profile name), used in output titles
    #: and notification subjects. Set directly or via a selected profile.
    site: str | None = None

    @classmethod
    def load(cls, path: str | Path, *, profile: str | None = None) -> AppConfig:
        """Load config, optionally overlaying a named ``profiles`` entry.

        A config may define ``profiles: {name: {<overrides>}}``; selecting one
        deep-merges its keys over the base document so several sites can share a
        single file. The chosen name also becomes the default ``site`` label.
        """
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        profiles = data.pop("profiles", {}) or {}
        if profile is not None:
            if profile not in profiles:
                available = ", ".join(sorted(profiles)) or "(none)"
                raise ConfigError(
                    f"unknown profile {profile!r}; available: {available}"
                )
            data = _deep_merge(data, profiles[profile])
            data.setdefault("site", profile)
        return cls.from_dict(data)

    @classmethod
    def profile_names(cls, path: str | Path) -> list[str]:
        """Return the profile names declared in ``path`` (empty if none)."""
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        return sorted((data.get("profiles") or {}).keys())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        networks = [_network(n) for n in data.get("networks", [])]
        hypervisors = [_hypervisor(h) for h in data.get("hypervisors", [])]
        linux_ssh = [_linux_ssh(s) for s in data.get("linux_ssh", [])]
        return cls(
            networks=networks,
            hypervisors=hypervisors,
            linux_ssh=linux_ssh,
            service_probes=data.get("service_probes", ["banner"]),
            enrichment=_enrichment(data.get("enrichment", {})),
            storage=_storage(data.get("storage", {})),
            notifications=_notifications(data.get("notifications", {})),
            workers=int(data.get("workers", 64)),
            output_dir=data.get("output_dir", "./out"),
            site=data.get("site"),
        )


def _network(data: dict[str, Any]) -> NetworkTarget:
    if "cidr" not in data:
        raise ConfigError("each network entry requires a 'cidr'")
    target_timeout = data.get("target_timeout")
    return NetworkTarget(
        cidr=data["cidr"],
        name=data.get("name"),
        vlan=data.get("vlan"),
        discovery=list(data.get("discovery", ["tcp"])),
        probe_ports=data.get("probe_ports"),
        timeout=float(data.get("timeout", 0.5)),
        workers=int(data.get("workers", 128)),
        rate_limit=float(data.get("rate_limit", 0.0)),
        target_timeout=float(target_timeout) if target_timeout is not None else None,
    )


def _hypervisor(data: dict[str, Any]) -> HypervisorTarget:
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


def _linux_ssh(data: dict[str, Any]) -> LinuxSshTarget:
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
        strict_host_key=bool(data.get("strict_host_key", True)),
    )


def _enrichment(data: dict[str, Any]) -> EnrichmentConfig:
    if not isinstance(data, dict):
        raise ConfigError("'enrichment' must be a mapping")
    return EnrichmentConfig(
        reverse_dns=bool(data.get("reverse_dns", True)),
        dhcp_leases=list(data.get("dhcp_leases", [])),
        os_fingerprint=bool(data.get("os_fingerprint", True)),
        classify=bool(data.get("classify", True)),
        snmp=_snmp(data.get("snmp", {})),
        rules=[_rule(r) for r in data.get("rules", [])],
    )


def _storage(data: dict[str, Any]) -> StorageConfig:
    if not isinstance(data, dict):
        raise ConfigError("'storage' must be a mapping")
    backend = str(data.get("backend", "json"))
    if backend not in ("json", "sqlite"):
        raise ConfigError(f"unsupported storage backend {backend!r}; use 'json' or 'sqlite'")
    return StorageConfig(
        backend=backend,
        keep_history=bool(data.get("keep_history", True)),
        stale_after_scans=int(data.get("stale_after_scans", 3)),
    )


def _notifications(data: dict[str, Any]) -> NotificationsConfig:
    if not isinstance(data, dict):
        raise ConfigError("'notifications' must be a mapping")
    email_data = data.get("email")
    return NotificationsConfig(
        enabled=bool(data.get("enabled", False)),
        on_change_only=bool(data.get("on_change_only", True)),
        webhooks=[_webhook(w) for w in data.get("webhooks", [])],
        email=_email(email_data) if email_data else None,
    )


def _webhook(data: dict[str, Any]) -> WebhookTarget:
    if not isinstance(data, dict) or "url" not in data:
        raise ConfigError("each notifications.webhooks entry requires a 'url'")
    fmt = str(data.get("format", "json"))
    if fmt not in ("json", "slack"):
        raise ConfigError(f"unsupported webhook format {fmt!r}; use 'json' or 'slack'")
    return WebhookTarget(
        url=data["url"],
        format=fmt,
        timeout=float(data.get("timeout", 10.0)),
        headers=dict(data.get("headers", {})),
    )


def _email(data: dict[str, Any]) -> EmailTarget:
    if not isinstance(data, dict):
        raise ConfigError("'notifications.email' must be a mapping")
    for required in ("host", "sender"):
        if required not in data:
            raise ConfigError(f"notifications.email requires '{required}'")
    recipients = data.get("recipients") or data.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    return EmailTarget(
        host=data["host"],
        sender=data["sender"],
        recipients=list(recipients),
        port=int(data.get("port", 25)),
        username=data.get("username"),
        password=_resolve_secret(data.get("password")),
        use_tls=bool(data.get("use_tls", False)),
        subject_prefix=str(data.get("subject_prefix", "")),
    )


def _snmp(data: dict[str, Any]) -> SnmpConfig:
    if not isinstance(data, dict):
        raise ConfigError("'enrichment.snmp' must be a mapping")
    version = str(data.get("version", "2c"))
    if version not in ("1", "2c"):
        raise ConfigError(f"unsupported snmp version {version!r}; use '1' or '2c'")
    return SnmpConfig(
        enabled=bool(data.get("enabled", False)),
        community=_resolve_secret(data.get("community")) or "public",
        version=version,
        port=int(data.get("port", 161)),
        timeout=float(data.get("timeout", 1.0)),
        retries=int(data.get("retries", 1)),
    )


def _rule(data: dict[str, Any]) -> ClassificationRule:
    if not isinstance(data, dict):
        raise ConfigError("each enrichment rule must be a mapping")
    return ClassificationRule(
        role=data.get("role"),
        tags=list(data.get("tags", [])),
        ports=[int(p) for p in data.get("ports", [])],
        services=list(data.get("services", [])),
        os_contains=data.get("os_contains"),
        vendor_contains=data.get("vendor_contains"),
        hostname_regex=data.get("hostname_regex"),
    )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base``, returning a new dict.

    Nested mappings merge key-by-key; every other value (including lists) is
    replaced wholesale by the overlay. Used to overlay a profile on the base
    config without mutating either source.
    """
    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _resolve_secret(ref: object) -> str | None:
    """Resolve a secret reference.

    * ``env:NAME``   -> value of environment variable ``NAME``
    * ``file:/path`` -> contents of the file (trimmed)
    * anything else  -> returned as-is, stringified (discouraged; emits no error)

    Accepts any scalar because YAML happily parses a bare numeric password as an
    ``int`` — we coerce it to ``str`` rather than crashing.
    """
    if ref is None or ref == "":
        return None
    if not isinstance(ref, str):
        return str(ref)
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
