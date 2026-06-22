"""Console logging for the CLI.

A single ``setup_logging`` call wires the package loggers to stderr so a scan or
report prints its progress as it goes. Timestamps are rendered in the Europe/Rome
zone to match the inventory's ``generated_at`` and the snapshot file names.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .timeutil import ROME


class _RomeFormatter(logging.Formatter):
    """Format the record time in the Europe/Rome zone, not the process locale."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, ROME)
        return dt.strftime(datefmt) if datefmt else dt.isoformat(timespec="seconds")


def setup_logging(verbose: int = 0) -> None:
    """Configure package logging. ``verbose`` 0 → INFO, 1+ → DEBUG.

    Idempotent: re-running replaces the handler rather than stacking duplicates.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(_RomeFormatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s"))

    root = logging.getLogger("myinventory")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
