"""Build channels from config and dispatch a change notification.

This is the glue between :class:`~myinventory.config.NotificationsConfig` and the
channel implementations. ``dispatch_change`` is what the CLI calls after a scan:
it gates on the opt-in flag and (by default) on there being an actual change,
renders one :class:`Notification` and hands it to every channel, collecting —
never raising — per-channel errors.
"""

from __future__ import annotations

import logging

from ..config import NotificationsConfig
from ..history import InventoryDiff
from .base import Notification, Notifier, notification_from_diff
from .email import EmailNotifier
from .webhook import WebhookNotifier

log = logging.getLogger(__name__)


def build_notifiers(cfg: NotificationsConfig) -> list[Notifier]:
    """Construct the channel objects declared in ``cfg``."""
    notifiers: list[Notifier] = []
    for wh in cfg.webhooks:
        notifiers.append(
            WebhookNotifier(wh.url, fmt=wh.format, timeout=wh.timeout, headers=wh.headers)
        )
    if cfg.email is not None:
        e = cfg.email
        notifiers.append(
            EmailNotifier(
                host=e.host,
                port=e.port,
                sender=e.sender,
                recipients=e.recipients,
                username=e.username,
                password=e.password,
                use_tls=e.use_tls,
                subject_prefix=e.subject_prefix,
            )
        )
    return notifiers


def dispatch_change(
    cfg: NotificationsConfig, diff: InventoryDiff, *, site: str | None = None
) -> list[str]:
    """Notify every channel of ``diff``; return a list of per-channel errors.

    No-ops (returning ``[]``) when notifications are disabled or when
    ``on_change_only`` is set and nothing changed.
    """
    if not cfg.enabled:
        return []
    if cfg.on_change_only and diff.is_empty:
        log.debug("notifications: no changes, nothing to send")
        return []

    notification: Notification = notification_from_diff(diff, site=site)
    errors: list[str] = []
    for notifier in build_notifiers(cfg):
        try:
            notifier.send(notification)
            log.info("notify/%s: sent (%s)", notifier.name, notification.summary)
        except Exception as exc:  # noqa: BLE001 - a bad channel must not abort
            errors.append(f"notify/{notifier.name}: {exc}")
            log.warning("notify/%s failed: %s", notifier.name, exc)
    return errors
