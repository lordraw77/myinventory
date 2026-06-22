"""Optional nmap-powered discovery + service/version detection.

When the ``nmap`` binary and the ``python-nmap`` wrapper are present (the
``[scan]`` extra), this backend does host discovery *and* service/version
fingerprinting in one pass — superseding the banner heuristics. When either is
missing it degrades gracefully: a clear, actionable error in the result rather
than a crash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..models import DiscoverySource, Host, Service
from .base import DiscoveryResult, HostDiscovery, register_discovery

if TYPE_CHECKING:
    from ..config import NetworkTarget


def _build_host(address: str, info: dict[str, Any]) -> Host:
    """Turn one host's nmap result (``nm[address]``) into a :class:`Host`."""
    mac = info.get("addresses", {}).get("mac")
    services: list[Service] = []
    for proto in ("tcp", "udp"):
        for port, pdata in info.get(proto, {}).items():
            if pdata.get("state") != "open":
                continue
            services.append(
                Service(
                    port=int(port),
                    protocol=proto,
                    name=pdata.get("name") or None,
                    product=pdata.get("product") or None,
                    version=pdata.get("version") or None,
                    state="open",
                    banner=pdata.get("extrainfo") or None,
                    source="nmap",
                )
            )
    return Host(
        # Key by address so results merge with other address-keyed sweeps.
        id=Host.compute_id(address=address),
        addresses=[address],
        mac=mac.lower() if mac else None,
        services=services,
        sources=[DiscoverySource.NMAP],
    )


def _arguments(target: NetworkTarget) -> str:
    args = ["-sV", "-T4"]
    if target.probe_ports:
        args += ["-p", ",".join(str(p) for p in target.probe_ports)]
    if target.target_timeout:
        args += ["--host-timeout", f"{int(target.target_timeout)}s"]
    return " ".join(args)


@register_discovery("nmap")
class NmapDiscovery(HostDiscovery):
    """Discover hosts and fingerprint services via the system ``nmap``."""

    def discover(self, target: object) -> DiscoveryResult:
        t = cast("NetworkTarget", target)
        result = DiscoveryResult()

        try:
            import nmap  # type: ignore
        except ImportError:
            result.errors.append(
                "nmap backend requires the 'scan' extra: pip install 'myinventory[scan]'"
            )
            return result

        try:
            scanner = nmap.PortScanner()
            scanner.scan(hosts=t.cidr, arguments=_arguments(t))
        except Exception as exc:  # noqa: BLE001 - nmap raises its own error types
            result.errors.append(f"nmap on {t.cidr}: {exc}")
            return result

        for address in scanner.all_hosts():
            info = scanner[address]
            if info.state() != "up":
                continue
            result.hosts.append(_build_host(address, info))
        return result
