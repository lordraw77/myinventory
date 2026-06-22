"""ARP host discovery for the local segment.

Reads the kernel's neighbour (ARP) table — ``ip neigh`` with a ``/proc/net/arp``
fallback — and reports each known neighbour as a host, crucially carrying its
**MAC address**. No raw sockets, no root, no dependencies.

Because it reflects what the kernel already resolved, it pairs naturally with an
active backend (``tcp``/``icmp``): run those first to populate the table, then
``arp`` annotates the discovered hosts with their MAC. An active ARP *scan*
(raw-socket who-has for silent hosts) can be added later behind ``[scan]``.
"""

from __future__ import annotations

import subprocess
from ipaddress import ip_network
from typing import TYPE_CHECKING, cast

from ..models import DiscoverySource, Host
from .base import DiscoveryResult, HostDiscovery, register_discovery

if TYPE_CHECKING:
    from ipaddress import _BaseNetwork

    from ..config import NetworkTarget

# Neighbour states that mean "we have a usable MAC for this IP".
_USABLE_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT", "NOARP"}


def _parse_ip_neigh(text: str, network: _BaseNetwork | None) -> list[Host]:
    """Parse ``ip neigh show`` output into hosts carrying their MAC.

    Example line::

        192.168.0.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
    """
    hosts: list[Host] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or "lladdr" not in parts:
            continue
        address = parts[0]
        mac = parts[parts.index("lladdr") + 1]
        state = parts[-1].upper()
        if state not in _USABLE_STATES:
            continue
        if network is not None and not _in_network(address, network):
            continue
        # Key by address so results merge with the tcp/icmp sweeps (which only
        # know the IP); the MAC rides along as an attribute.
        hosts.append(
            Host(
                id=Host.compute_id(address=address),
                addresses=[address],
                mac=mac.lower(),
                sources=[DiscoverySource.ARP],
            )
        )
    return hosts


def _in_network(address: str, network: _BaseNetwork) -> bool:
    from ipaddress import ip_address

    try:
        return ip_address(address) in network
    except ValueError:
        return False


@register_discovery("arp")
class ArpNeighborDiscovery(HostDiscovery):
    """Report local-segment hosts (with MACs) from the kernel neighbour table."""

    def discover(self, target: object) -> DiscoveryResult:
        t = cast("NetworkTarget", target)
        result = DiscoveryResult()
        try:
            network: _BaseNetwork | None = ip_network(t.cidr, strict=False)
        except ValueError as exc:
            result.errors.append(f"invalid cidr {t.cidr!r}: {exc}")
            return result

        text = self._read_table()
        if text is None:
            result.errors.append(
                f"arp on {t.cidr}: could not read neighbour table "
                "(no 'ip' binary and no /proc/net/arp)"
            )
            return result
        result.hosts.extend(_parse_ip_neigh(text, network))
        return result

    @staticmethod
    def _read_table() -> str | None:
        try:
            proc = subprocess.run(
                ["ip", "neigh", "show"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.SubprocessError):
            pass
        return _read_proc_arp()


def _read_proc_arp() -> str | None:
    """Fallback: translate ``/proc/net/arp`` into ``ip neigh``-style lines."""
    from pathlib import Path

    path = Path("/proc/net/arp")
    if not path.exists():
        return None
    lines = []
    for row in path.read_text().splitlines()[1:]:  # skip header
        cols = row.split()
        if len(cols) >= 6:
            ip_addr, _hw_type, _flags, mac, _mask, dev = cols[:6]
            if mac != "00:00:00:00:00:00":
                lines.append(f"{ip_addr} dev {dev} lladdr {mac} REACHABLE")
    return "\n".join(lines)
