"""Stale-host detection: which hosts haven't been seen in the last N scans.

The cumulative ``inventory.json`` never drops a host (a re-scan is an upsert), so
"is this host gone?" cannot be answered from the merged state alone. It is
answered from the *snapshot history*: a host is stale when its stable ID is
absent from every one of the most recent ``scans`` raw-scan snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Host, Inventory


@dataclass
class StaleHost:
    """A host in the cumulative inventory that recent scans stopped seeing."""

    host: Host
    missed_scans: int  # number of recent snapshots it was absent from

    @property
    def label(self) -> str:
        return self.host.hostname or self.host.primary_address or self.host.id


def stale_hosts(
    inventory: Inventory,
    snapshots: list[Inventory],
    *,
    scans: int = 3,
) -> list[StaleHost]:
    """Return hosts absent from each of the last ``scans`` snapshots.

    ``snapshots`` is the raw-scan history, oldest first. With fewer than
    ``scans`` snapshots available there is not enough history to call anything
    stale, so the result is empty.
    """
    if scans < 1 or len(snapshots) < scans:
        return []

    recent = snapshots[-scans:]
    seen_recently: set[str] = set()
    for snap in recent:
        seen_recently.update(snap.hosts)

    out: list[StaleHost] = []
    for host in inventory.hosts.values():
        if host.id not in seen_recently:
            out.append(StaleHost(host=host, missed_scans=len(recent)))
    out.sort(key=lambda s: s.label)
    return out
