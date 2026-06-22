"""Tests for the scan concurrency lockfile."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myinventory.lock import FileLock, LockError


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "scan.lock")
    with lock:
        assert (tmp_path / "scan.lock").exists()
    assert not (tmp_path / "scan.lock").exists()


def test_second_acquire_by_live_holder_raises(tmp_path: Path) -> None:
    path = tmp_path / "scan.lock"
    # A live PID owns the lock — a second acquire must back off.
    with FileLock(path), pytest.raises(LockError):
        FileLock(path).acquire()


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "scan.lock"
    # A lockfile naming a PID that cannot exist — simulate a crashed scan.
    path.write_text("2147483646")
    with FileLock(path):
        assert int(path.read_text()) == os.getpid()
    assert not path.exists()


def test_garbage_lockfile_is_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "scan.lock"
    path.write_text("not-a-pid")
    with FileLock(path):
        assert int(path.read_text()) == os.getpid()
