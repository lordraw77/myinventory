"""The notification payload and the channel interface.

A :class:`Notification` is a rendered, channel-agnostic summary of one scan's
changes — a title, a one-line summary, a Markdown body and the raw diff dict for
JSON consumers. Building it from an :class:`~myinventory.history.InventoryDiff`
lives here so every channel sends the same content.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..history import InventoryDiff


@dataclass
class Notification:
    """A channel-agnostic, pre-rendered change summary."""

    title: str
    summary: str
    body_markdown: str
    diff: dict[str, Any] = field(default_factory=dict)


class Notifier(ABC):
    """A delivery channel. ``send`` raises on failure; the dispatcher fails soft."""

    #: Short channel name for error messages (e.g. ``"webhook"``).
    name: str = "notifier"

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Deliver ``notification`` or raise on failure."""


def notification_from_diff(
    diff: InventoryDiff, *, site: str | None = None
) -> Notification:
    """Render a :class:`Notification` from a structured inventory diff."""
    scope = f"[{site}] " if site else ""
    title = f"{scope}myinventory: {diff.summary()}"
    when = diff.new_generated_at or "latest scan"

    lines = [f"# {title}", "", f"_Scan {when} — {diff.summary()}_", ""]

    if diff.hosts_added:
        lines += ["## Hosts added", ""]
        for h in diff.hosts_added:
            label = h.hostname or h.primary_address or h.id
            lines.append(f"- {label} (`{h.primary_address or h.id}`) — {h.role.value}")
        lines.append("")

    if diff.hosts_removed:
        lines += ["## Hosts removed", ""]
        for h in diff.hosts_removed:
            label = h.hostname or h.primary_address or h.id
            lines.append(f"- {label} (`{h.primary_address or h.id}`)")
        lines.append("")

    if diff.hosts_changed:
        lines += ["## Hosts changed", ""]
        for c in diff.hosts_changed:
            bits = [f"{fc.field} {fc.before}→{fc.after}" for fc in c.fields]
            bits += [f"+{s}" for s in c.services_added]
            bits += [f"-{s}" for s in c.services_removed]
            detail = "; ".join(bits) if bits else "service/version drift"
            lines.append(f"- {c.label}: {detail}")
        lines.append("")

    if diff.vms_added or diff.vms_removed or diff.vms_changed:
        lines += ["## Virtual machines", ""]
        for v in diff.vms_added:
            lines.append(f"- added: {v.name}")
        for v in diff.vms_removed:
            lines.append(f"- removed: {v.name}")
        for vc in diff.vms_changed:
            lines.append(f"- drifted: {vc.name}")
        lines.append("")

    body = "\n".join(lines).rstrip() + "\n"
    return Notification(
        title=title,
        summary=diff.summary(),
        body_markdown=body,
        diff=diff.to_dict(),
    )
