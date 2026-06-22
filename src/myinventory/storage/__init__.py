"""Persistence for the inventory."""

from .repository import (
    InventoryRepository,
    JsonInventoryRepository,
    SqliteInventoryRepository,
    make_repository,
)

__all__ = [
    "InventoryRepository",
    "JsonInventoryRepository",
    "SqliteInventoryRepository",
    "make_repository",
]
