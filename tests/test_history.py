"""Tests for Milestone 5 — change tracking & reporting.

Covers the pure diff/changelog/stale helpers, the snapshot history kept by both
repository backends, and the SQLite backend round-tripping the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myinventory.history import (
    build_changelog,
    diff_inventories,
    stale_hosts,
)
from myinventory.models import (
    Host,
    HostRole,
    Inventory,
    PowerState,
    Service,
    VirtualMachine,
)
from myinventory.storage import (
    JsonInventoryRepository,
    SqliteInventoryRepository,
)


def _host(addr: str, **kw: object) -> Host:
    return Host(id=f"ip:{addr}", addresses=[addr], **kw)  # type: ignore[arg-type]


# --- diff -----------------------------------------------------------------
def test_diff_detects_added_removed_and_unchanged() -> None:
    old = Inventory()
    old.upsert_host(_host("10.0.0.1", hostname="a"))
    old.upsert_host(_host("10.0.0.2", hostname="b"))

    new = Inventory()
    new.upsert_host(_host("10.0.0.1", hostname="a"))  # unchanged
    new.upsert_host(_host("10.0.0.3", hostname="c"))  # added; .2 removed

    d = diff_inventories(old, new)
    assert [h.id for h in d.hosts_added] == ["ip:10.0.0.3"]
    assert [h.id for h in d.hosts_removed] == ["ip:10.0.0.2"]
    assert d.hosts_changed == []
    assert not d.is_empty


def test_diff_detects_field_and_service_changes() -> None:
    old = Inventory()
    old.upsert_host(
        _host(
            "10.0.0.1",
            hostname="web",
            role=HostRole.UNKNOWN,
            services=[Service(port=80, name="http", product="nginx", version="1.24")],
        )
    )
    new = Inventory()
    new.upsert_host(
        _host(
            "10.0.0.1",
            hostname="web",
            role=HostRole.PHYSICAL,
            os="Ubuntu 24.04",
            services=[
                Service(port=80, name="http", product="nginx", version="1.25"),
                Service(port=443, name="https"),
            ],
        )
    )

    d = diff_inventories(old, new)
    assert len(d.hosts_changed) == 1
    change = d.hosts_changed[0]
    field_names = {c.field for c in change.fields}
    assert "role" in field_names
    assert "os" in field_names
    assert change.services_added == ["https"]
    assert change.services_removed == []
    assert len(change.services_changed) == 1  # nginx version bump


def test_diff_detects_vm_drift() -> None:
    old = Inventory()
    old.upsert_vm(
        VirtualMachine(
            id="vm-1", name="db", hypervisor_id="ip:10.0.0.1", backend="proxmox",
            power_state=PowerState.RUNNING, memory_mb=2048,
        )
    )
    new = Inventory()
    new.upsert_vm(
        VirtualMachine(
            id="vm-1", name="db", hypervisor_id="ip:10.0.0.1", backend="proxmox",
            power_state=PowerState.STOPPED, memory_mb=4096,
        )
    )
    new.upsert_vm(
        VirtualMachine(id="vm-2", name="cache", hypervisor_id="ip:10.0.0.1", backend="proxmox")
    )

    d = diff_inventories(old, new)
    assert [v.id for v in d.vms_added] == ["vm-2"]
    assert len(d.vms_changed) == 1
    fields = {c.field for c in d.vms_changed[0].fields}
    assert {"power state", "memory (MB)"} <= fields


def test_diff_summary_and_empty() -> None:
    inv = Inventory()
    inv.upsert_host(_host("10.0.0.1"))
    d = diff_inventories(inv, inv)
    assert d.is_empty
    assert d.summary() == "no changes"


# --- changelog ------------------------------------------------------------
def test_build_changelog_newest_first() -> None:
    s1 = Inventory(generated_at="2026-01-01T00:00:00+00:00")
    s1.upsert_host(_host("10.0.0.1", hostname="a"))

    s2 = Inventory(generated_at="2026-01-02T00:00:00+00:00")
    s2.upsert_host(_host("10.0.0.1", hostname="a"))
    s2.upsert_host(_host("10.0.0.2", hostname="b"))

    md = build_changelog([("s1", s1), ("s2", s2)])
    assert md.startswith("# Changelog")
    assert "Hosts added" in md
    assert "**b**" in md


def test_build_changelog_needs_two_snapshots() -> None:
    s1 = Inventory()
    md = build_changelog([("s1", s1)])
    assert "No prior scans" in md


# --- stale detection ------------------------------------------------------
def test_stale_hosts_flags_missing() -> None:
    cumulative = Inventory()
    cumulative.upsert_host(_host("10.0.0.1"))
    cumulative.upsert_host(_host("10.0.0.2"))  # disappeared

    # Three recent scans, none of which saw .2
    snaps = []
    for _ in range(3):
        s = Inventory()
        s.upsert_host(_host("10.0.0.1"))
        snaps.append(s)

    stale = stale_hosts(cumulative, snaps, scans=3)
    assert [s.host.id for s in stale] == ["ip:10.0.0.2"]
    assert stale[0].missed_scans == 3


def test_stale_hosts_needs_enough_history() -> None:
    cumulative = Inventory()
    cumulative.upsert_host(_host("10.0.0.1"))
    assert stale_hosts(cumulative, [Inventory()], scans=3) == []


# --- repository history (both backends) -----------------------------------
@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_repository_keeps_snapshots(tmp_path: Path, backend: str) -> None:
    if backend == "json":
        repo = JsonInventoryRepository(tmp_path / "inventory.json")
    else:
        repo = SqliteInventoryRepository(tmp_path / "inventory.db")

    first = Inventory()
    first.upsert_host(_host("10.0.0.1", hostname="a"))
    repo.save_merged(first)

    second = Inventory()
    second.upsert_host(_host("10.0.0.3", hostname="c"))
    repo.save_merged(second)

    # Cumulative state has both hosts (merge never drops one).
    cumulative = repo.load()
    assert cumulative is not None
    assert set(cumulative.hosts) == {"ip:10.0.0.1", "ip:10.0.0.3"}

    # History recorded each raw scan separately, oldest first.
    snaps = repo.snapshots()
    assert len(snaps) == 2
    assert set(snaps[0][1].hosts) == {"ip:10.0.0.1"}
    assert set(snaps[1][1].hosts) == {"ip:10.0.0.3"}


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_repository_round_trips(tmp_path: Path, backend: str) -> None:
    if backend == "json":
        repo = JsonInventoryRepository(tmp_path / "inventory.json")
    else:
        repo = SqliteInventoryRepository(tmp_path / "inventory.db")

    inv = Inventory()
    inv.upsert_host(
        _host("10.0.0.1", hostname="a", services=[Service(port=22, name="ssh")])
    )
    repo.save(inv)
    loaded = repo.load()
    assert loaded is not None
    assert loaded.to_dict() == inv.to_dict()


def test_save_merged_can_skip_history(tmp_path: Path) -> None:
    repo = JsonInventoryRepository(tmp_path / "inventory.json")
    inv = Inventory()
    inv.upsert_host(_host("10.0.0.1"))
    repo.save_merged(inv, keep_history=False)
    assert repo.snapshot_ids() == []
