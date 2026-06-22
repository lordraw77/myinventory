"""Virtualization backend contract + registry.

A backend connects to one hypervisor / cluster management endpoint and returns
the VMs it hosts plus the hypervisor host(s) themselves. The orchestrator later
correlates VM IPs with network-discovered hosts.

Lifecycle: ``connect() -> collect() -> close()``. ``collect`` is the only
required method; the default ``connect``/``close`` are no-ops so simple backends
can ignore them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..models import Host, VirtualMachine


@dataclass
class BackendResult:
    """What one backend run produced."""

    #: The hypervisor node(s) — physical hosts running the virtualization stack.
    hosts: list[Host] = field(default_factory=list)
    #: The guests enumerated from those hosts.
    vms: list[VirtualMachine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class VirtualizationBackend(ABC):
    """Base class for all hypervisor backends."""

    #: Registry key, matched against ``type`` in the hypervisor config.
    name: str = ""

    def __init__(self, **options: object) -> None:
        self.options = options

    def connect(self, target: object) -> None:  # noqa: B027 - optional override, default no-op
        """Open a session to ``target`` (a ``HypervisorTarget``). Optional."""

    @abstractmethod
    def collect(self, target: object) -> BackendResult:
        """Enumerate hypervisor hosts and their VMs."""
        raise NotImplementedError

    def close(self) -> None:  # noqa: B027 - optional override, default no-op
        """Release any session resources. Optional."""

    def run(self, target: object) -> BackendResult:
        """Convenience wrapper: connect → collect → close, errors captured."""
        try:
            self.connect(target)
            return self.collect(target)
        except Exception as exc:  # noqa: BLE001 - fail soft, never abort census
            return BackendResult(errors=[f"{self.name}: {exc}"])
        finally:
            self.close()


# --- registry -------------------------------------------------------------
_REGISTRY: dict[str, type[VirtualizationBackend]] = {}


def register_backend(
    name: str,
) -> Callable[[type[VirtualizationBackend]], type[VirtualizationBackend]]:
    def _decorator(cls: type[VirtualizationBackend]) -> type[VirtualizationBackend]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _decorator


def get_backend(name: str, **options: object) -> VirtualizationBackend:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown virtualization backend {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](**options)


def available() -> list[str]:
    return sorted(_REGISTRY)
