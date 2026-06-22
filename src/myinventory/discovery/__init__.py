"""Host-discovery plugins: find which addresses are alive on a network."""

from .base import HostDiscovery, DiscoveryResult, register_discovery, get_discovery, available

# Importing the concrete backends registers them as a side effect.
from . import tcp  # noqa: F401,E402

__all__ = [
    "HostDiscovery",
    "DiscoveryResult",
    "register_discovery",
    "get_discovery",
    "available",
]
