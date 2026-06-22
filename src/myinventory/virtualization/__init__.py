"""Virtualization backends: enumerate VMs from hypervisor management APIs."""

# Importing the concrete backends registers them as a side effect. Each guards
# its own optional SDK import, so this stays safe without the [virt] extra.
from . import libvirt  # noqa: F401,E402
from . import proxmox  # noqa: F401,E402
from . import vmware  # noqa: F401,E402
from .base import (
    BackendResult,
    VirtualizationBackend,
    available,
    get_backend,
    register_backend,
)

__all__ = [
    "BackendResult",
    "VirtualizationBackend",
    "register_backend",
    "get_backend",
    "available",
]
