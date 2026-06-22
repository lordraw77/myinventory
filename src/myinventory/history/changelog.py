"""Render inventory diffs to a Markdown changelog.

A changelog page is the diff history read top-down: the newest scan first, each
section describing what changed relative to the scan before it. It is a pure
function of a sequence of snapshots, so — like the other renderers — it can be
regenerated anytime without touching the network.
"""

from __future__ import annotations

from ..models import Inventory
from .diff import InventoryDiff, diff_inventories


def build_changelog(snapshots: list[tuple[str, Inventory]]) -> str:
    """Build ``changelog.md`` from ``snapshots`` (oldest first).

    Each consecutive pair becomes a section; sections are emitted newest first.
    With fewer than two snapshots there is nothing to compare yet.
    """
    lines = ["# Changelog", ""]
    if len(snapshots) < 2:
        lines += ["_No prior scans to compare yet._", ""]
        return "\n".join(lines).rstrip() + "\n"

    sections: list[str] = []
    for (_, old), (new_id, new) in zip(snapshots, snapshots[1:]):
        diff = diff_inventories(old, new)
        sections.append(_section(new_id, new.generated_at, diff))
    # Newest scan first.
    for section in reversed(sections):
        lines.append(section)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_diff_section(title: str, diff: InventoryDiff) -> str:
    """Render a single diff as a standalone Markdown block (used by the CLI)."""
    return _section(title, diff.new_generated_at, diff)


def _section(snapshot_id: str, generated_at: str | None, diff: InventoryDiff) -> str:
    when = generated_at or snapshot_id
    lines = [f"## {when}", "", f"_{diff.summary()}_", ""]
    if diff.is_empty:
        return "\n".join(lines).rstrip()

    if diff.hosts_added:
        lines += ["### Hosts added", ""]
        for h in diff.hosts_added:
            label = h.hostname or h.primary_address or h.id
            lines.append(f"- **{label}** (`{h.primary_address or h.id}`) — {h.role.value}")
        lines.append("")

    if diff.hosts_removed:
        lines += ["### Hosts removed", ""]
        for h in diff.hosts_removed:
            label = h.hostname or h.primary_address or h.id
            lines.append(f"- **{label}** (`{h.primary_address or h.id}`)")
        lines.append("")

    if diff.hosts_changed:
        lines += ["### Hosts changed", ""]
        for c in diff.hosts_changed:
            lines.append(f"- **{c.label}**")
            for fc in c.fields:
                lines.append(f"  - {fc.field}: `{_fmt(fc.before)}` → `{_fmt(fc.after)}`")
            for svc in c.services_added:
                lines.append(f"  - service added: {svc}")
            for svc in c.services_removed:
                lines.append(f"  - service removed: {svc}")
            for sc in c.services_changed:
                lines.append(f"  - service {sc.field}: {_fmt(sc.before)} → {_fmt(sc.after)}")
        lines.append("")

    if diff.vms_added or diff.vms_removed or diff.vms_changed:
        lines += ["### Virtual machines", ""]
        for v in diff.vms_added:
            lines.append(f"- added: **{v.name}**")
        for v in diff.vms_removed:
            lines.append(f"- removed: **{v.name}**")
        for vc in diff.vms_changed:
            details = "; ".join(
                f"{fc.field} {_fmt(fc.before)}→{_fmt(fc.after)}" for fc in vc.fields
            )
            lines.append(f"- drifted: **{vc.name}** ({details})")
        lines.append("")

    return "\n".join(lines).rstrip()


def _fmt(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)
