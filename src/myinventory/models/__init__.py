"""Normalized inventory data model.

These dataclasses are the single contract spoken by every other component:
discovery and virtualization backends *produce* them, storage *persists* them,
and renderers *consume* them. They contain no I/O and no backend-specific logic.
"""

from .host import DiscoverySource, Host, HostRole
from .inventory import Inventory
from .network import Network
from .service import Service
from .vm import PowerState, VirtualMachine

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
