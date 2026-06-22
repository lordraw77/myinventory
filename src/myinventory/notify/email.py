"""Email notifier — send a change summary over SMTP.

Plain :mod:`smtplib` and :mod:`email.message` from the standard library, so no
extra dependency. STARTTLS is opt-in (``use_tls``); auth is used only when a
username is configured. The body is the notification's Markdown text sent as
``text/plain`` — readable in any client without an HTML pipeline.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .base import Notification, Notifier


class EmailNotifier(Notifier):
    name = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int = 25,
        sender: str,
        recipients: list[str],
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        subject_prefix: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.subject_prefix = subject_prefix
        self.timeout = timeout

    def _message(self, n: Notification) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"{self.subject_prefix}{n.title}"
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(n.body_markdown)
        return msg

    def send(self, notification: Notification) -> None:
        if not self.recipients:
            raise RuntimeError("email notifier has no recipients configured")
        msg = self._message(notification)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)
