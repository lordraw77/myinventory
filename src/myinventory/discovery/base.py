"""Host-discovery plugin contract + registry.

A discovery backend answers one question: *which addresses on this network are
alive, and how do I know?* It returns bare :class:`Host` objects (address +
source); service detail is the job of the service-discovery stage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..models import Host

# Forward reference to config type to avoid an import cycle at module load.
# from ..config import NetworkTarget  (imported lazily by callers)


@dataclass
class DiscoveryResult:
    """Output of one discovery run against one network target."""

    hosts: list[Host] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class HostDiscovery(ABC):
    """Base class for all host-discovery backends.

    Subclasses declare a unique :pyattr:`name` and implement :meth:`discover`.
    Heavy/optional third-party imports (e.g. scapy) must live *inside* the
    module so a base install without ``[scan]`` still imports cleanly.
    """

    #: Registry key, also used as the ``DiscoverySource`` value.
    name: str = ""

    def __init__(self, **options: object) -> None:
        self.options = options

    @abstractmethod
    def discover(self, target: object) -> DiscoveryResult:
        """Scan ``target`` (a ``NetworkTarget``) and return live hosts."""
        raise NotImplementedError


# --- registry -------------------------------------------------------------
_REGISTRY: dict[str, type[HostDiscovery]] = {}


def register_discovery(name: str) -> Callable[[type[HostDiscovery]], type[HostDiscovery]]:
    """Class decorator that registers a discovery backend under ``name``."""

    def _decorator(cls: type[HostDiscovery]) -> type[HostDiscovery]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorator


def get_discovery(name: str, **options: object) -> HostDiscovery:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown discovery backend {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](**options)


def available() -> list[str]:
    return sorted(_REGISTRY)
