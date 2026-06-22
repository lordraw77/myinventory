"""Time helpers — every human-facing timestamp uses the Europe/Rome zone.

Keeping this in one place means ``generated_at`` / ``first_seen`` / ``last_seen``,
the snapshot filenames and the log lines all agree on the same wall clock, so a
``142500Z`` UTC stamp never disagrees with the ``16:25`` a Rome operator expects.
The stamps are timezone-aware (they carry the ``+02:00`` / ``+01:00`` offset),
so they stay unambiguous and correctly comparable across the DST boundary.
"""

from __future__ import annotations

from datetime import datetime

try:  # zoneinfo ships with Python 3.9+, but the tz database may be absent.
    from zoneinfo import ZoneInfo

    ROME: ZoneInfo | None = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover - exercised only without tzdata installed
    ROME = None


def now() -> datetime:
    """Current time, aware, in the Europe/Rome zone (or the host's local zone)."""
    if ROME is not None:
        return datetime.now(ROME)
    return datetime.now().astimezone()


def now_iso() -> str:
    """ISO-8601 Rome timestamp at second precision, e.g. ``2026-06-22T16:25:00+02:00``."""
    return now().replace(microsecond=0).isoformat()


def snapshot_stamp() -> str:
    """Filesystem-safe Rome stamp for snapshot ids, e.g. ``20260622T162500``.

    Rome wall clock rather than UTC so the history file names line up with the
    timestamps inside them; lexicographic order stays chronological save for the
    one repeated hour at the autumn DST roll-back.
    """
    return now().strftime("%Y%m%dT%H%M%S")
