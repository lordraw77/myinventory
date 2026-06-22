"""Change tracking: diff scans, build changelogs, detect stale hosts (M5).

The cumulative inventory is the source of truth; the *snapshot history* kept by
the repository is what makes change tracking possible. These helpers are pure
functions of the model — diffing two inventories, rendering the diff history to a
Markdown changelog, and flagging hosts recent scans stopped seeing.
"""

from .changelog import build_changelog, render_diff_section
from .diff import (
    FieldChange,
    HostChange,
    InventoryDiff,
    VmChange,
    diff_inventories,
)
from .stale import StaleHost, stale_hosts

__all__ = [
    "InventoryDiff",
    "HostChange",
    "VmChange",
    "FieldChange",
    "diff_inventories",
    "build_changelog",
    "render_diff_section",
    "StaleHost",
    "stale_hosts",
]
