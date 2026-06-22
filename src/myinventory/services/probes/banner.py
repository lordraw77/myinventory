"""Unauthenticated banner-grab probe — the dependency-free reference probe.

For each candidate port it connects, optionally nudges the service (an HTTP
request on web ports), reads the first bytes, and matches them against the
signature table. Falls back to the well-known-port name when a service stays
silent.
"""

from __future__ import annotations

import socket

from ...models import Host, Service
from ..base import ServiceProbe, register_probe
from .signatures import WELL_KNOWN_PORTS, identify

# Ports the probe will try when the host has no known-open ports yet.
DEFAULT_PORTS = sorted(WELL_KNOWN_PORTS)
HTTP_PORTS = {80, 8080, 8006, 9090}


@register_probe("banner")
class BannerProbe(ServiceProbe):
    """Identify services by their connect-time banner."""

    def probe(self, host: Host) -> list[Service]:
        ports = self._candidate_ports(host)
        timeout = float(self.options.get("timeout", 1.0))  # type: ignore[arg-type]
        address = host.primary_address
        if not address:
            return []

        services: list[Service] = []
        for port in ports:
            svc = self._probe_port(address, port, timeout)
            if svc is not None:
                services.append(svc)
        return services

    def _candidate_ports(self, host: Host) -> list[int]:
        known = [s.port for s in host.services if s.protocol == "tcp"]
        return known or DEFAULT_PORTS

    def _probe_port(self, address: str, port: int, timeout: float) -> Service | None:
        try:
            with socket.create_connection((address, port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                if port in HTTP_PORTS:
                    sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
                raw = sock.recv(256)
        except OSError:
            return None

        banner = raw.decode("latin-1", errors="replace").strip()
        name, product, version = identify(banner, port)
        return Service(
            port=port,
            protocol="tcp",
            name=name,
            product=product,
            version=version,
            state="open",
            banner=banner or None,
            source="banner",
        )
