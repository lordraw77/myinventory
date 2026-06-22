"""TCP-connect host discovery — a dependency-free reference backend.

Treats a host as alive if *any* of a small set of common ports accepts a
connection. Works through firewalls that drop ICMP, and needs no root.

This is the reference implementation used to validate the plugin contract and
the pipeline end-to-end. ICMP/ARP backends (which need raw sockets / scapy)
arrive in milestone 1 — see ``docs/roadmap.md``.
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_network
from typing import TYPE_CHECKING, cast

from ..models import DiscoverySource, Host
from .base import DiscoveryResult, HostDiscovery, register_discovery

if TYPE_CHECKING:
    from ..config import NetworkTarget

# Ports likely to be open on *something* worth inventorying.
DEFAULT_PROBE_PORTS = (22, 80, 443, 445, 3389, 8006, 902)


@register_discovery("tcp")
class TcpConnectDiscovery(HostDiscovery):
    """Find live hosts by attempting TCP connections to common ports."""

    def discover(self, target: object) -> DiscoveryResult:
        cidr = cast("NetworkTarget", target).cidr
        ports = list(getattr(target, "probe_ports", None) or DEFAULT_PROBE_PORTS)
        timeout = float(getattr(target, "timeout", 0.5))
        workers = int(getattr(target, "workers", 128))

        result = DiscoveryResult()
        try:
            addresses = [str(ip) for ip in ip_network(cidr, strict=False).hosts()]
        except ValueError as exc:
            result.errors.append(f"invalid cidr {cidr!r}: {exc}")
            return result

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for addr, open_ports in zip(
                addresses,
                pool.map(lambda a: self._scan(a, ports, timeout), addresses),
            ):
                if open_ports:
                    result.hosts.append(self._make_host(addr))
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
