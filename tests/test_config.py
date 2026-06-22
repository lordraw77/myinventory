"""Config-loading tests: secret resolution, scalar coercion, M1 network fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from myinventory.config import AppConfig, ConfigError


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(text)
    return cfg


def test_numeric_password_is_coerced_to_str(tmp_path: Path) -> None:
    # Regression: YAML parses a bare numeric password as int; must not crash.
    cfg = _write(
        tmp_path,
        """
linux_ssh:
  - host: 192.168.0.1
    username: root
    password: 280977
    sudo_password: 280977
""",
    )
    config = AppConfig.load(cfg)
    target = config.linux_ssh[0]
    assert target.password == "280977"
    assert target.sudo_password == "280977"
    assert target.sudo is True  # implied by a sudo_password being present


def test_network_rate_limit_and_target_timeout_parsed(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
networks:
  - cidr: 10.0.0.0/24
    discovery: [tcp, arp]
    rate_limit: 50
    target_timeout: 30
""",
    )
    net = AppConfig.load(cfg).networks[0]
    assert net.discovery == ["tcp", "arp"]
    assert net.rate_limit == 50.0
    assert net.target_timeout == 30.0


def test_env_secret_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PVE_TOKEN", "s3cr3t")
    cfg = _write(
        tmp_path,
        """
hypervisors:
  - type: proxmox
    host: 1.2.3.4
    secret: env:MY_PVE_TOKEN
""",
    )
    assert AppConfig.load(cfg).hypervisors[0].secret == "s3cr3t"


def test_missing_env_secret_raises(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
hypervisors:
  - type: proxmox
    host: 1.2.3.4
    secret: env:DEFINITELY_NOT_SET_12345
""",
    )
    with pytest.raises(ConfigError):
        AppConfig.load(cfg)
