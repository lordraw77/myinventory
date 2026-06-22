"""Milestone-6 config: profiles overlay + notifications parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from myinventory.config import AppConfig, ConfigError


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(text)
    return cfg


def test_profile_overlays_base_and_sets_site(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
workers: 8
storage:
  backend: json
networks:
  - cidr: 10.0.0.0/24
profiles:
  prod:
    workers: 64
    storage:
      backend: sqlite
    networks:
      - cidr: 192.168.1.0/24
""",
    )
    assert AppConfig.profile_names(cfg) == ["prod"]

    base = AppConfig.load(cfg)
    assert base.workers == 8
    assert base.storage.backend == "json"
    assert base.site is None

    prod = AppConfig.load(cfg, profile="prod")
    assert prod.workers == 64
    # nested mapping merges key-by-key
    assert prod.storage.backend == "sqlite"
    assert prod.storage.keep_history is True
    # list is replaced wholesale
    assert [n.cidr for n in prod.networks] == ["192.168.1.0/24"]
    # selected profile name becomes the default site label
    assert prod.site == "prod"


def test_unknown_profile_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "profiles:\n  a: {}\n")
    with pytest.raises(ConfigError):
        AppConfig.load(cfg, profile="nope")


def test_notifications_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_PW", "hunter2")
    cfg = _write(
        tmp_path,
        """
notifications:
  enabled: true
  webhooks:
    - url: https://hooks.example/abc
      format: slack
  email:
    host: smtp.example
    sender: inv@example
    recipients: ops@example
    username: inv
    password: env:SMTP_PW
    use_tls: true
""",
    )
    n = AppConfig.load(cfg).notifications
    assert n.enabled is True
    assert n.on_change_only is True
    assert len(n.webhooks) == 1
    assert n.webhooks[0].format == "slack"
    assert n.email is not None
    assert n.email.recipients == ["ops@example"]  # scalar coerced to list
    assert n.email.password == "hunter2"
    assert n.email.use_tls is True


def test_bad_webhook_format_raises(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
notifications:
  webhooks:
    - url: https://x
      format: carrier-pigeon
""",
    )
    with pytest.raises(ConfigError):
        AppConfig.load(cfg)
