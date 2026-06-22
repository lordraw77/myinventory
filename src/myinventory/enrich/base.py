"""Enrichment plugin contract + registry.

An *enricher* runs after discovery, virtualization and correlation. Where a
discovery backend answers "which addresses are alive" and a service probe
answers "what runs on this port", an enricher answers "what *is* this host, and
what do we already know about it from other sources" — names from DNS/DHCP, an
OS guess from heuristics, vendor from MAC OUI, role from a rule set.

Each enricher mutates the :class:`~myinventory.models.Inventory` in place and
returns an :class:`EnrichResult`. Like every other plugin, heavy/optional
imports (e.g. ``pysnmp``) live *inside* the concrete module so a base install
imports cleanly and degrades gracefully when an extra is missing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..config import EnrichmentConfig
    from ..models import Inventory


@dataclass
class EnrichResult:
    """Outcome of one enricher pass over the whole inventory."""

    applied: int = 0  # number of hosts this pass changed
    errors: list[str] = field(default_factory=list)


class Enricher(ABC):
    """Base class for all enrichers."""

    #: Registry key.
    name: str = ""

    def __init__(self, **options: object) -> None:
        self.options = options

    @abstractmethod
    def enrich(self, inventory: Inventory, config: EnrichmentConfig) -> EnrichResult:
        """Annotate hosts in ``inventory`` using ``config``; never raise."""
        raise NotImplementedError


# --- registry -------------------------------------------------------------
_REGISTRY: dict[str, type[Enricher]] = {}


def register_enricher(name: str) -> Callable[[type[Enricher]], type[Enricher]]:
    def _decorator(cls: type[Enricher]) -> type[Enricher]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorator


def get_enricher(name: str, **options: object) -> Enricher:
    if name not in _REGISTRY:
        raise KeyError(f"unknown enricher {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**options)


def available() -> list[str]:
    return sorted(_REGISTRY)
