"""Service-discovery plugins: identify what a host runs."""

from .base import ServiceProbe, register_probe, get_probe, available

# Importing the concrete probes registers them as a side effect.
from . import probes  # noqa: F401,E402

__all__ = ["ServiceProbe", "register_probe", "get_probe", "available"]
