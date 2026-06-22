"""Normalized inventory data model.

These dataclasses are the single contract spoken by every other component:
discovery and virtualization backends *produce* them, storage *persists* them,
and renderers *consume* them. They contain no I/O and no backend-specific logic.
"""

from .service import Service
from .host import Host, HostRole, DiscoverySource
from .vm import VirtualMachine, PowerState
from .network import Network
from .inventory import Inventory

__all__ = [
    "Service",
    "Host",
    "HostRole",
    "DiscoverySource",
    "VirtualMachine",
    "PowerState",
    "Network",
    "Inventory",
]
