"""Integration test: real TCP discovery + banner probe against a live service.

A lightweight, CI-friendly stand-in for the docker-compose lab — it starts an
in-process TCP server that emits an SSH-style banner on connect, then drives the
actual ``tcp`` discovery backend and the ``banner`` probe end-to-end against it.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator

import pytest

from myinventory.config import NetworkTarget
from myinventory.discovery import get_discovery
from myinventory.models import Host, Service
from myinventory.services import get_probe

BANNER = b"SSH-2.0-OpenSSH_9.6p1 Debian-2\r\n"


@pytest.fixture()
def ssh_like_server() -> Iterator[int]:
    """Bind a localhost server that greets each client with an SSH banner."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        srv.settimeout(0.25)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (TimeoutError, OSError):
                continue
            try:
                conn.sendall(BANNER)
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        srv.close()
        thread.join(timeout=2.0)


def test_tcp_discovery_finds_localhost(ssh_like_server: int) -> None:
    target = NetworkTarget(cidr="127.0.0.1/32", probe_ports=[ssh_like_server], timeout=1.0)
    result = get_discovery("tcp").discover(target)
    assert [h.primary_address for h in result.hosts] == ["127.0.0.1"]


def test_banner_probe_identifies_live_service(ssh_like_server: int) -> None:
    # A host whose open port was established by discovery; the probe upgrades it.
    host = Host(
        id="ip:127.0.0.1",
        addresses=["127.0.0.1"],
        services=[Service(port=ssh_like_server, state="open")],
    )
    services = get_probe("banner", timeout=1.0).probe(host)

    match = next(s for s in services if s.port == ssh_like_server)
    assert match.name == "ssh"
    assert match.product == "OpenSSH"
    assert match.version == "9.6p1"
