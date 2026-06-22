"""Tests for banner signature matching + version extraction (Milestone 1)."""

from __future__ import annotations

import pytest

from myinventory.services.probes.signatures import identify


@pytest.mark.parametrize(
    ("banner", "port", "expected"),
    [
        ("SSH-2.0-OpenSSH_9.6p1 Debian-2", 22, ("ssh", "OpenSSH", "9.6p1")),
        ("SSH-2.0-dropbear_2022.83", 22, ("ssh", "Dropbear", "2022.83")),
        ("HTTP/1.1 200 OK\r\nServer: nginx/1.25.3", 80, ("http", "nginx", "1.25.3")),
        (
            "HTTP/1.1 403\r\nServer: Apache/2.4.57 (Debian)",
            80,
            ("http", "Apache", "2.4.57"),
        ),
        ("220 mail.example.com ESMTP Postfix", 25, ("smtp", "Postfix", None)),
        (
            "5.5.5-10.11.6-MariaDB-1:10.11.6+maria~deb12",
            3306,
            ("mysql", "MariaDB", "10.11.6"),
        ),
        ("$redis_version:7.2.4\r\n", 6379, ("redis", "Redis", "7.2.4")),
    ],
)
def test_identify_extracts_product_and_version(
    banner: str, port: int, expected: tuple[str | None, str | None, str | None]
) -> None:
    assert identify(banner, port) == expected


def test_identify_falls_back_to_well_known_port() -> None:
    # No banner (binary protocol): name comes from the port table, no product.
    assert identify("", 5432) == ("postgresql", None, None)
    assert identify("", 3389) == ("rdp", None, None)


def test_identify_unknown_silent_port() -> None:
    assert identify("", 49152) == (None, None, None)
