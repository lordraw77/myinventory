"""Change notifications (Milestone 6) — opt-in webhook / email alerts.

After a scan merges, the orchestrator-level workflow computes the diff against
the previous snapshot and, when something changed, dispatches a
:class:`Notification` to every configured channel. Channels are best-effort: a
failing webhook or SMTP server records an error and never aborts the scan.

Both built-in channels use only the standard library (``urllib`` /
``smtplib``), so notifications add no install-time dependency.
"""

from .base import Notification, Notifier, notification_from_diff
from .dispatch import dispatch_change
from .email import EmailNotifier
from .webhook import WebhookNotifier

__all__ = [
    "Notification",
    "Notifier",
    "notification_from_diff",
    "dispatch_change",
    "EmailNotifier",
    "WebhookNotifier",
]
