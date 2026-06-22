"""Webhook notifier — POST a change summary to an HTTP endpoint.

Two payload shapes are supported:

* ``json``  — ``{"title", "summary", "body", "diff"}`` for generic consumers.
* ``slack`` — ``{"text": ...}`` for Slack/Mattermost incoming-webhook URLs.

Uses :mod:`urllib.request` from the standard library so it adds no dependency.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from .base import Notification, Notifier


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(
        self,
        url: str,
        *,
        fmt: str = "json",
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.fmt = fmt
        self.timeout = timeout
        self.headers = headers or {}

    def _payload(self, n: Notification) -> dict[str, Any]:
        if self.fmt == "slack":
            return {"text": f"*{n.title}*\n{n.summary}"}
        return {
            "title": n.title,
            "summary": n.summary,
            "body": n.body_markdown,
            "diff": n.diff,
        }

    def send(self, notification: Notification) -> None:
        data = json.dumps(self._payload(notification)).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", **self.headers},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise RuntimeError(f"webhook returned HTTP {status}")
