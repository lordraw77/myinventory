"""Hostname resolution: reverse DNS + DHCP-lease lookup.

Two cheap, dependency-free sources of a friendly name for a host that discovery
only knew by IP/MAC:

* **Reverse DNS** — a parallel ``gethostbyaddr`` sweep over every address.
* **DHCP leases** — parse the lease database a homelab router/server already
  keeps (dnsmasq's ``*.leases`` or ISC ``dhcpd.leases``) for the client-supplied
  hostname, matched back to a host by MAC (preferred) or IP.

DHCP runs first (a client's own name is usually the more meaningful one); reverse
DNS fills any host still missing a name. Neither overwrites a hostname that a
stronger source (SSH/SNMP) already set.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import TYPE_CHECKING

from ..discovery._sweep import sweep
from .base import Enricher, EnrichResult, register_enricher

if TYPE_CHECKING:
    from ..config import EnrichmentConfig
    from ..models import Inventory


# --- pure lease parsers ---------------------------------------------------
def parse_dnsmasq_leases(text: str) -> list[tuple[str, str, str | None]]:
    """Parse a dnsmasq lease file into ``(mac, ip, hostname)`` tuples.

    Lines look like ``<expiry> <mac> <ip> <hostname> <client-id>`` where a
    hostname of ``*`` means the client supplied none.
    """
    out: list[tuple[str, str, str | None]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        _expiry, mac, ip, name = parts[0], parts[1], parts[2], parts[3]
        if ":" not in mac:  # not a MAC in field 2 — not a dnsmasq lease line
            continue
        hostname = None if name == "*" else name
        out.append((mac.lower(), ip, hostname))
    return out


def parse_isc_leases(text: str) -> list[tuple[str, str, str | None]]:
    """Parse an ISC ``dhcpd.leases`` file into ``(mac, ip, hostname)`` tuples.

    Later ``lease`` blocks for the same IP override earlier ones, matching how
    ISC dhcpd appends; we keep the last occurrence per IP.
    """
    by_ip: dict[str, tuple[str, str, str | None]] = {}
    ip: str | None = None
    mac = ""
    hostname: str | None = None
    for raw in text.splitlines():
        line = raw.strip().rstrip(";")
        if line.startswith("lease "):
            ip = line.split()[1]
            mac, hostname = "", None
        elif line.startswith("hardware ethernet "):
            mac = line.split()[-1].lower()
        elif line.startswith("client-hostname "):
            hostname = line.split('"')[1] if '"' in line else None
        elif line == "}" and ip is not None:
            by_ip[ip] = (mac, ip, hostname)
            ip = None
    return list(by_ip.values())


def parse_leases(text: str) -> list[tuple[str, str, str | None]]:
    """Auto-detect the lease format and parse it."""
    if "lease " in text and "{" in text:
        return parse_isc_leases(text)
    return parse_dnsmasq_leases(text)


# --- reverse-DNS resolver (module-level so tests can monkeypatch it) -------
def _reverse_lookup(address: str) -> str | None:
    """Return the PTR hostname for ``address`` or ``None`` if it has none."""
    try:
        return socket.gethostbyaddr(address)[0]
    except OSError:
        return None


@register_enricher("hostname")
class HostnameEnricher(Enricher):
    """Fill in missing hostnames from DHCP leases and reverse DNS."""

    def enrich(self, inventory: Inventory, config: EnrichmentConfig) -> EnrichResult:
        result = EnrichResult()
        if config.dhcp_leases:
            result.applied += self._from_dhcp(inventory, config, result)
        if config.reverse_dns:
            result.applied += self._from_rdns(inventory)
        return result

    # --- DHCP leases ------------------------------------------------------
    def _from_dhcp(
        self, inventory: Inventory, config: EnrichmentConfig, result: EnrichResult
    ) -> int:
        by_mac: dict[str, str] = {}
        by_ip: dict[str, str] = {}
        for path in config.dhcp_leases:
            try:
                text = Path(path).expanduser().read_text()
            except OSError as exc:
                result.errors.append(f"enrich/hostname: lease file {path}: {exc}")
                continue
            for mac, ip, name in parse_leases(text):
                if not name:
                    continue
                if mac:
                    by_mac.setdefault(mac, name)
                by_ip.setdefault(ip, name)

        applied = 0
        for host in inventory.hosts.values():
            if host.hostname:
                continue
            name = (host.mac and by_mac.get(host.mac.lower())) or next(
                (by_ip[a] for a in host.addresses if a in by_ip), None
            )
            if name:
                host.hostname = name
                host.extra["dhcp_hostname"] = name
                applied += 1
        return applied

    # --- reverse DNS ------------------------------------------------------
    @staticmethod
    def _from_rdns(inventory: Inventory) -> int:
        pending = [
            h.primary_address
            for h in inventory.hosts.values()
            if h.primary_address and not h.hostname
        ]
        if not pending:
            return 0
        names, _ = sweep(pending, _reverse_lookup, workers=min(64, len(pending)))

        applied = 0
        for host in inventory.hosts.values():
            if host.hostname or not host.primary_address:
                continue
            name = names.get(host.primary_address)
            if name:
                host.hostname = name
                host.extra["rdns"] = name
                applied += 1
        return applied
