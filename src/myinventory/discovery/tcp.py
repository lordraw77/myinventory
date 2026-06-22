"""TCP-connect host discovery — a dependency-free, firewall-friendly backend.

Treats a host as alive if *any* of a small set of common ports accepts a
connection. Works through firewalls that drop ICMP, and needs no root. Honors
the network target's ``rate_limit`` and ``target_timeout`` budgets.
"""

from __future__ import annotations

import socket
from ipaddress import ip_network
from typing import TYPE_CHECKING, cast

from ..models import DiscoverySource, Host
from ._sweep import sweep
from .base import DiscoveryResult, HostDiscovery, register_discovery

if TYPE_CHECKING:
    from ..config import NetworkTarget

# Ports likely to be open on *something* worth inventorying.
DEFAULT_PROBE_PORTS = (22, 80, 443, 445, 3389, 8006, 902)


@register_discovery("tcp")
class TcpConnectDiscovery(HostDiscovery):
    """Find live hosts by attempting TCP connections to common ports."""

    def discover(self, target: object) -> DiscoveryResult:
        t = cast("NetworkTarget", target)
        ports = list(getattr(target, "probe_ports", None) or DEFAULT_PROBE_PORTS)
        timeout = float(getattr(target, "timeout", 0.5))
        workers = int(getattr(target, "workers", 128))

        result = DiscoveryResult()
        try:
            addresses = [str(ip) for ip in ip_network(t.cidr, strict=False).hosts()]
        except ValueError as exc:
            result.errors.append(f"invalid cidr {t.cidr!r}: {exc}")
            return result

        scanned, timed_out = sweep(
            addresses,
            lambda a: self._scan(a, ports, timeout),
            workers=workers,
            rate_limit=float(getattr(target, "rate_limit", 0.0)),
            target_timeout=getattr(target, "target_timeout", None),
        )
        for addr, open_ports in scanned.items():
            if open_ports:
                result.hosts.append(self._make_host(addr))
        if timed_out:
            result.errors.append(f"tcp on {t.cidr}: target_timeout reached, partial result")
        return result

    @staticmethod
    def _scan(address: str, ports: list[int], timeout: float) -> list[int]:
        open_ports: list[int] = []
        for port in ports:
            try:
                with socket.create_connection((address, port), timeout=timeout):
                    open_ports.append(port)
            except OSError:
                continue
        return open_ports

    @staticmethod
    def _make_host(address: str) -> Host:
        return Host(
            id=Host.compute_id(address=address),
            addresses=[address],
            sources=[DiscoverySource.TCP],
        )
