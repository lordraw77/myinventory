"""Tests for the JSON storage repository: persist + merge by stable ID."""

from __future__ import annotations

from pathlib import Path

from myinventory.models import Host, HostRole, Inventory, Service
from myinventory.storage import JsonInventoryRepository


def test_load_missing_returns_none(tmp_path: Path) -> None:
    repo = JsonInventoryRepository(tmp_path / "inventory.json")
    assert repo.load() is None


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    repo = JsonInventoryRepository(tmp_path / "nested" / "inventory.json")
    inv = Inventory()
    inv.upsert_host(Host(id="ip:10.0.0.1", addresses=["10.0.0.1"], hostname="a"))

    repo.save(inv)
    loaded = repo.load()

    assert loaded is not None
    assert loaded.to_dict() == inv.to_dict()


def test_save_merged_merges_by_stable_id(tmp_path: Path) -> None:
    repo = JsonInventoryRepository(tmp_path / "inventory.json")

    first = Inventory()
    first.upsert_host(
        Host(id="ip:10.0.0.1", addresses=["10.0.0.1"], role=HostRole.UNKNOWN)
    )
    repo.save_merged(first)

    second = Inventory()
    second.upsert_host(
        Host(
            id="ip:10.0.0.1",
            addresses=["10.0.0.1"],
            hostname="late-name",
            role=HostRole.NAS,
            services=[Service(port=445, name="smb")],
        )
    )
    second.upsert_host(Host(id="ip:10.0.0.2", addresses=["10.0.0.2"]))

    merged = repo.save_merged(second)

    # Same record was updated, not duplicated; the new host was added.
    assert set(merged.hosts) == {"ip:10.0.0.1", "ip:10.0.0.2"}
    host = merged.hosts["ip:10.0.0.1"]
    assert host.hostname == "late-name"
    assert host.role == HostRole.NAS
    assert len(host.services) == 1

    # And the merge is durable: reloading from disk yields the same state.
    reloaded = repo.load()
    assert reloaded is not None
    assert reloaded.to_dict() == merged.to_dict()
