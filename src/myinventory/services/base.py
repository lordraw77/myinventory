"""Service-probe plugin contract + registry.

A probe inspects a single :class:`Host` and returns the :class:`Service`
objects it can identify. Probes are layered: a cheap unauthenticated banner
probe always runs; richer authenticated probes (SSH/SNMP) run only when
credentials are configured.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Type

from ..models import Host, Service


class ServiceProbe(ABC):
    """Base class for all service-discovery probes."""

    #: Registry key.
    name: str = ""

    def __init__(self, **options: object) -> None:
        self.options = options

    @abstractmethod
    def probe(self, host: Host) -> List[Service]:
        """Inspect ``host`` and return any services found (may be empty)."""
        raise NotImplementedError


# --- registry -------------------------------------------------------------
_REGISTRY: Dict[str, Type[ServiceProbe]] = {}


def register_probe(name: str) -> Callable[[Type[ServiceProbe]], Type[ServiceProbe]]:
    def _decorator(cls: Type[ServiceProbe]) -> Type[ServiceProbe]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorator


def get_probe(name: str, **options: object) -> ServiceProbe:
    if name not in _REGISTRY:
        raise KeyError(f"unknown probe {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**options)


def available() -> List[str]:
    return sorted(_REGISTRY)
