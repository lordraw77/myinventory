"""Host-discovery plugins: find which addresses are alive on a network."""

# Importing the concrete backends registers them as a side effect.
from . import arp, icmp, nmap, tcp  # noqa: F401,E402
from .base import DiscoveryResult, HostDiscovery, available, get_discovery, register_discovery

__all__ = [
    "HostDiscovery",
    "DiscoveryResult",
    "register_discovery",
    "get_discovery",
    "available",
]
