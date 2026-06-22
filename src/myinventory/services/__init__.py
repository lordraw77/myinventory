"""Service-discovery plugins: identify what a host runs."""

# Importing the concrete probes registers them as a side effect.
from . import probes  # noqa: F401,E402
from .base import ServiceProbe, available, get_probe, register_probe

__all__ = ["ServiceProbe", "register_probe", "get_probe", "available"]
