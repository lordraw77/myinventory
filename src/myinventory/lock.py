"""A cross-process lockfile to serialize scans (Milestone 6).

A scan touches the network, mutates the cumulative inventory and snapshot
history, and can run for minutes. Two scans racing on the same output directory
would interleave snapshots and corrupt the merge, so a scheduled run (systemd
timer / cron) that overlaps a slow previous run must back off rather than pile
up.

:class:`FileLock` is an advisory, PID-stamped lock acquired by atomically
creating a lockfile (``O_CREAT | O_EXCL``). It is a context manager:

    with FileLock(out / ".myinventory.lock"):
        ...  # only one process at a time gets here

A lock left behind by a process that has since died is detected (the recorded
PID is gone) and reclaimed, so a crash mid-scan does not wedge the schedule
forever.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from types import TracebackType

log = logging.getLogger(__name__)


class LockError(RuntimeError):
    """Raised when the lock is already held by another live process."""


class FileLock:
    """An advisory, PID-stamped lockfile usable as a context manager."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._try_create():
            return
        # The lockfile exists. If the recorded process is gone, it is stale and
        # we may steal it; otherwise a live scan owns it and we must back off.
        holder = self._read_pid()
        if holder is not None and _pid_alive(holder):
            raise LockError(
                f"another scan is running (pid {holder}); lock held at {self.path}"
            )
        log.warning("reclaiming stale lock at %s (holder pid %s gone)", self.path, holder)
        self._steal()

    def release(self) -> None:
        if not self._acquired:
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        self._acquired = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    # --- internals --------------------------------------------------------
    def _try_create(self) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        self._acquired = True
        return True

    def _read_pid(self) -> int | None:
        try:
            return int(self.path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def _steal(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        if not self._try_create():
            # Someone beat us to the reclaim in the meantime.
            raise LockError(f"lock at {self.path} was re-acquired during reclaim")


def _pid_alive(pid: int) -> bool:
    """Return whether ``pid`` is a live process (best effort, POSIX)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists but is owned by someone else — still alive.
        return True
    return True
