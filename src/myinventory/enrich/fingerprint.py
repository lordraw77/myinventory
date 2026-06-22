"""OS fingerprint heuristics — a best-effort guess, not nmap.

Three weak signals combined into one guess, in order of trust:

1. **SNMP ``sysDescr``** (when the SNMP enricher ran first) — usually states the
   OS outright.
2. **Open-port / service profile** — RDP+SMB without SSH smells like Windows;
   SSH smells like a Unix; only SNMP/management ports smell like an appliance.
3. **TTL** of a single ping — the *initial* TTL the stack used (64 → Linux/Unix,
   128 → Windows, 255 → a router/switch) survives a few hops, so rounding the
   observed value up to the nearest of those three is a decent tie-breaker.

The guess only fills :attr:`Host.os` when nothing better is already set; the raw
signals always land in ``host.extra['os_fingerprint']`` for transparency.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from .base import Enricher, EnrichResult, register_enricher

if TYPE_CHECKING:
    from ..config import EnrichmentConfig
    from ..models import Host, Inventory

_INITIAL_TTLS = (64, 128, 255)

_UNIX_HINTS = {"ssh"}


def _looks_windows(ports: set[int]) -> bool:
    """True only for the *full* Windows RPC/RDP surface.

    SMB (445) alone is a weak signal — Linux Samba and NAS boxes expose it too —
    so we require RDP, or msrpc (135) paired with SMB.
    """
    return 3389 in ports or (135 in ports and 445 in ports)


def initial_ttl(observed: int) -> int | None:
    """Round an observed TTL up to the nearest common initial TTL."""
    for base in _INITIAL_TTLS:
        if observed <= base:
            return base
    return None


def guess_os(
    *,
    ttl: int | None,
    ports: set[int],
    service_names: set[str],
    banners: str = "",
    snmp_descr: str | None = None,
) -> tuple[str | None, str]:
    """Return ``(os, confidence)`` where confidence is ``high|medium|low``.

    ``os`` is ``None`` when no signal is conclusive enough to guess.
    """
    low_banner = banners.lower()

    # 1) SNMP sysDescr is the strongest signal.
    if snmp_descr:
        descr = snmp_descr.lower()
        for needle, label in _DESCR_OS:
            if needle in descr:
                return label, "high"

    # 2) Distro/product strings leaking through banners.
    for needle, label in _BANNER_OS:
        if needle in low_banner:
            return label, "high"

    # 3) Port/service profile.
    has_ssh = bool(service_names & _UNIX_HINTS) or 22 in ports
    windows = _looks_windows(ports)
    if windows and not has_ssh:
        return "Windows", "medium"
    if has_ssh and not windows:
        # SSH strongly implies Unix; TTL refines (255 → an appliance with SSH).
        if _ttl_os(ttl) == "network device":
            return "Network device", "medium"
        return "Linux/Unix", "medium"

    # 4) TTL alone as a last resort.
    os_from_ttl = _ttl_os(ttl)
    if os_from_ttl is not None:
        return os_from_ttl.title() if os_from_ttl != "Windows" else "Windows", "low"
    return None, "low"


def _ttl_os(ttl: int | None) -> str | None:
    if ttl is None:
        return None
    base = initial_ttl(ttl)
    if base is None:
        return None
    return {64: "Linux/Unix", 128: "Windows", 255: "network device"}.get(base)


# (needle, label) tables — order matters, specific before generic.
_DESCR_OS: tuple[tuple[str, str], ...] = (
    ("windows", "Windows"),
    ("mikrotik", "RouterOS"),
    ("routeros", "RouterOS"),
    ("cisco ios", "Cisco IOS"),
    ("edgeos", "EdgeOS"),
    ("vyos", "VyOS"),
    ("junos", "Junos"),
    ("ubuntu", "Ubuntu"),
    ("debian", "Debian"),
    ("freebsd", "FreeBSD"),
    ("darwin", "macOS"),
    ("linux", "Linux"),
)

_BANNER_OS: tuple[tuple[str, str], ...] = (
    ("ubuntu", "Ubuntu"),
    ("debian", "Debian"),
    ("centos", "CentOS"),
    ("rocky", "Rocky Linux"),
    ("fedora", "Fedora"),
    ("freebsd", "FreeBSD"),
    ("win32", "Windows"),
    ("windows", "Windows"),
)


# --- TTL probe (module-level so tests can monkeypatch it) -----------------
_TTL_RE = re.compile(r"ttl[=\s:]+(\d+)", re.IGNORECASE)


def _probe_ttl(address: str, timeout: float = 1.0) -> int | None:
    """Send a single ping and parse the reply TTL, or ``None`` on failure."""
    cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), address]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 2.0
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _TTL_RE.search(proc.stdout)
    return int(match.group(1)) if match else None


@register_enricher("fingerprint")
class OsFingerprintEnricher(Enricher):
    """Guess each host's OS from TTL, banners and its open-port profile."""

    def enrich(self, inventory: Inventory, config: EnrichmentConfig) -> EnrichResult:
        result = EnrichResult()
        for host in inventory.hosts.values():
            if self._fingerprint(host):
                result.applied += 1
        return result

    def _fingerprint(self, host: Host) -> bool:
        ports = {s.port for s in host.services}
        names = {s.name for s in host.services if s.name}
        banners = " ".join(s.banner for s in host.services if s.banner)
        snmp = host.extra.get("snmp_descr")

        ttl: int | None = None
        if host.primary_address:
            ttl = _probe_ttl(host.primary_address)

        os_guess, confidence = guess_os(
            ttl=ttl,
            ports=ports,
            service_names=names,
            banners=banners,
            snmp_descr=snmp,
        )
        if os_guess is None and ttl is None:
            return False

        host.extra["os_fingerprint"] = {
            "os": os_guess,
            "confidence": confidence,
            "ttl": ttl,
            "initial_ttl": initial_ttl(ttl) if ttl is not None else None,
        }
        # Only fill the OS field when a stronger source hasn't already set it.
        if os_guess and not host.os:
            host.os = os_guess
            return True
        return os_guess is not None
