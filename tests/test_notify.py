"""Tests for change notifications: rendering, channels and dispatch gating."""

from __future__ import annotations

import json
from typing import Any

import pytest

from myinventory.config import EmailTarget, NotificationsConfig, WebhookTarget
from myinventory.history import diff_inventories
from myinventory.models import Host, HostRole, Inventory, Service
from myinventory.notify import (
    Notification,
    dispatch_change,
    notification_from_diff,
)
from myinventory.notify.email import EmailNotifier
from myinventory.notify.webhook import WebhookNotifier


def _changed_diff():  # type: ignore[no-untyped-def]
    old = Inventory()
    old.upsert_host(Host(id="ip:10.0.0.1", addresses=["10.0.0.1"]))
    new = Inventory()
    new.upsert_host(Host(id="ip:10.0.0.1", addresses=["10.0.0.1"]))
    new.upsert_host(
        Host(
            id="ip:10.0.0.2",
            addresses=["10.0.0.2"],
            hostname="nas",
            role=HostRole.NAS,
            services=[Service(port=445, name="smb")],
        )
    )
    return diff_inventories(old, new)


def test_notification_from_diff_renders_summary_and_body() -> None:
    n = notification_from_diff(_changed_diff(), site="home")
    assert "[home]" in n.title
    assert "+1 hosts" in n.summary
    assert "Hosts added" in n.body_markdown
    assert "nas" in n.body_markdown
    assert n.diff["hosts_added"]


def test_webhook_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Resp:
        status = 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fake_urlopen(req: Any, timeout: float = 0) -> _Resp:
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    WebhookNotifier("https://hook.example").send(
        notification_from_diff(_changed_diff())
    )
    assert captured["url"] == "https://hook.example"
    assert captured["body"]["summary"].startswith("+1 hosts")
    assert "diff" in captured["body"]


def test_webhook_slack_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Resp:
        status = 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=0: captured.update(body=json.loads(req.data.decode()))
        or _Resp(),
    )
    WebhookNotifier("https://hook.example", fmt="slack").send(
        Notification(title="T", summary="S", body_markdown="B")
    )
    assert captured["body"] == {"text": "*T*\nS"}


def test_email_uses_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float = 0) -> None:
            sent["host"] = host
            sent["port"] = port

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def starttls(self) -> None:
            sent["tls"] = True

        def login(self, user: str, pw: str) -> None:
            sent["login"] = (user, pw)

        def send_message(self, msg: Any) -> None:
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    EmailNotifier(
        host="smtp.example",
        port=587,
        sender="inv@example",
        recipients=["ops@example"],
        username="inv",
        password="pw",
        use_tls=True,
        subject_prefix="[inv] ",
    ).send(notification_from_diff(_changed_diff()))

    assert sent["host"] == "smtp.example"
    assert sent["tls"] is True
    assert sent["login"] == ("inv", "pw")
    assert sent["to"] == "ops@example"
    assert sent["subject"].startswith("[inv] ")


def test_dispatch_disabled_is_noop() -> None:
    cfg = NotificationsConfig(enabled=False, webhooks=[WebhookTarget(url="https://x")])
    assert dispatch_change(cfg, _changed_diff()) == []


def test_dispatch_on_change_only_skips_empty_diff() -> None:
    cfg = NotificationsConfig(
        enabled=True, on_change_only=True, webhooks=[WebhookTarget(url="https://x")]
    )
    empty = diff_inventories(Inventory(), Inventory())
    assert dispatch_change(cfg, empty) == []


def test_dispatch_collects_channel_errors() -> None:
    # An unroutable email host makes the channel fail; the error is collected,
    # not raised.
    cfg = NotificationsConfig(
        enabled=True,
        email=EmailTarget(host="smtp.invalid", sender="a@b", recipients=[]),
    )
    errors = dispatch_change(cfg, _changed_diff())
    assert len(errors) == 1
    assert errors[0].startswith("notify/email:")
