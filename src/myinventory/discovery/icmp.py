"""ICMP ping-sweep host discovery.

Sends one echo request per address using the system ``ping`` binary, so it
needs no raw-socket privileges and no third-party dependency. A host is alive if
``ping`` exits 0. Honors the target's ``rate_limit`` and ``target_timeout``.

Raw-socket ICMP (faster, but root-only) can be added later behind the ``[scan]``
extra; the subprocess approach is the dependency-free default.
"""

from __future__ import annotations

import platform
import subprocess
from ipaddress import ip_network
from math import ceil
from typing import TYPE_CHECKING, cast

from ..models import DiscoverySource, Host
from ._sweep import sweep
from .base import DiscoveryResult, HostDiscovery, register_discovery

if TYPE_CHECKING:
    from ..config import NetworkTarget

_IS_WINDOWS = platform.system().lower().startswith("win")


def _ping_command(address: str, timeout: float) -> list[str]:
    """Build a single-echo ``ping`` command line for the current platform."""
    if _IS_WINDOWS:
        # -w takes milliseconds on Windows.
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), address]
    # -c count, -W per-reply timeout in (whole) seconds on Linux/macOS.
    return ["ping", "-c", "1", "-W", str(max(1, ceil(timeout))), address]


def _alive(address: str, timeout: float) -> bool:
    try:
        proc = subprocess.run(
            _ping_command(address, timeout),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@register_discovery("icmp")
class IcmpPingDiscovery(HostDiscovery):
    """Find live hosts with an ICMP echo (ping) sweep."""

    def discover(self, target: object) -> DiscoveryResult:
        t = cast("NetworkTarget", target)
        timeout = float(getattr(target, "timeout", 0.5))
        workers = int(getattr(target, "workers", 128))

        result = DiscoveryResult()
        try:
            addresses = [str(ip) for ip in ip_network(t.cidr, strict=False).hosts()]
        except ValueError as exc:
            result.errors.append(f"invalid cidr {t.cidr!r}: {exc}")
            return result

        swept, timed_out = sweep(
            addresses,
            lambda a: _alive(a, timeout),
            workers=workers,
            rate_limit=float(getattr(target, "rate_limit", 0.0)),
            target_timeout=getattr(target, "target_timeout", None),
        )
        for addr, up in swept.items():
            if up:
                result.hosts.append(
                    Host(
                        id=Host.compute_id(address=addr),
                        addresses=[addr],
                        sources=[DiscoverySource.ICMP],
                    )
                )
        if timed_out:
            result.errors.append(
                f"icmp on {t.cidr}: target_timeout reached, partial result"
            )
        return result
