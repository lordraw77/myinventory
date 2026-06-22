"""Inventory persistence.

The default implementation writes a single ``inventory.json``. A new scan is
merged into the prior one (by stable ID) so the file is an evolving source of
truth, not a snapshot that loses history. The abstract base lets a SQLite
backend slot in later (roadmap M4) without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import Inventory


class InventoryRepository(ABC):
    @abstractmethod
    def load(self) -> Optional[Inventory]:
        """Return the stored inventory, or ``None`` if there is none yet."""

    @abstractmethod
    def save(self, inventory: Inventory) -> None:
        """Persist ``inventory``, replacing any prior state."""

    def save_merged(self, inventory: Inventory) -> Inventory:
        """Merge ``inventory`` over stored state, persist, and return the result."""
        prior = self.load()
        if prior is not None:
            prior.merge(inventory)
            merged = prior
        else:
            merged = inventory
        self.save(merged)
        return merged


class JsonInventoryRepository(InventoryRepository):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> Optional[Inventory]:
        if not self.path.exists():
            return None
        return Inventory.from_json(self.path.read_text())

    def save(self, inventory: Inventory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(inventory.to_json())
