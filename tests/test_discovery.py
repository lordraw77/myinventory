"""Tests for the Milestone 1 discovery backends and the sweep helper."""

from __future__ import annotations

import time

import pytest

from myinventory.config import NetworkTarget
from myinventory.discovery import available, get_discovery
from myinventory.discovery import icmp as icmp_mod
from myinventory.discovery._sweep import sweep
from myinventory.discovery.arp import _parse_ip_neigh
from myinventory.discovery.nmap import _build_host
from myinventory.models import DiscoverySource, Host, Inventory


def test_all_backends_registered() -> None:
    assert set(available()) == {"arp", "icmp", "nmap", "tcp"}


def test_address_keyed_backends_merge_instead_of_duplicating() -> None:
    # Regression: tcp (IP only) and arp (IP + MAC) must collapse to one host.
    inv = Inventory()
    inv.upsert_host(
        Host(
            id=Host.compute_id(address="192.168.0.5"),
            addresses=["192.168.0.5"],
            sources=[DiscoverySource.TCP],
        )
    )
    inv.upsert_host(
        Host(
            id=Host.compute_id(address="192.168.0.5"),
            addresses=["192.168.0.5"],
            mac="aa:bb:cc:dd:ee:05",
            sources=[DiscoverySource.ARP],
        )
    )

    assert len(inv.hosts) == 1
    host = inv.hosts["ip:192.168.0.5"]
    assert host.mac == "aa:bb:cc:dd:ee:05"  # MAC from arp merged into the tcp host
    assert set(host.sources) == {DiscoverySource.TCP, DiscoverySource.ARP}


# --- sweep ----------------------------------------------------------------
def test_sweep_collects_all_results() -> None:
    results, timed_out = sweep(["a", "b", "c"], lambda x: x.upper(), workers=4)
    assert results == {"a": "A", "b": "B", "c": "C"}
    assert timed_out is False


def test_sweep_honors_target_timeout() -> None:
    def slow(_: str) -> bool:
        time.sleep(0.5)
        return True

    results, timed_out = sweep(
        [str(i) for i in range(20)], slow, workers=2, target_timeout=0.1
    )
    assert timed_out is True
    assert len(results) < 20  # budget hit before everything finished


# --- icmp -----------------------------------------------------------------
def test_icmp_discovery_reports_alive_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend only .1 answers the ping.
    monkeypatch.setattr(icmp_mod, "_alive", lambda addr, timeout: addr.endswith(".1"))
    target = NetworkTarget(cidr="192.0.2.0/30", timeout=0.1)

    result = get_discovery("icmp").discover(target)

    assert [h.primary_address for h in result.hosts] == ["192.0.2.1"]
    assert result.hosts[0].sources == [DiscoverySource.ICMP]


def test_icmp_ping_command_shapes() -> None:
    cmd = icmp_mod._ping_command("10.0.0.1", 0.5)
    assert cmd[0] == "ping" and "10.0.0.1" in cmd


# --- arp ------------------------------------------------------------------
def test_arp_parses_neighbour_table_with_macs() -> None:
    from ipaddress import ip_network

    text = (
        "192.168.0.1 dev eth0 lladdr aa:bb:cc:dd:ee:01 REACHABLE\n"
        "192.168.0.5 dev eth0 lladdr AA:BB:CC:DD:EE:05 STALE\n"
        "192.168.0.9 dev eth0  INCOMPLETE\n"          # no MAC -> skipped
        "192.168.0.13 dev eth0 lladdr aa:bb:cc:dd:ee:13 FAILED\n"  # bad state -> skipped
        "10.0.0.1 dev eth0 lladdr aa:bb:cc:dd:ee:99 REACHABLE\n"   # off-subnet -> skipped
    )
    hosts = _parse_ip_neigh(text, ip_network("192.168.0.0/24"))

    by_addr = {h.primary_address: h for h in hosts}
    assert set(by_addr) == {"192.168.0.1", "192.168.0.5"}
    assert by_addr["192.168.0.5"].mac == "aa:bb:cc:dd:ee:05"  # normalized lower-case
    assert by_addr["192.168.0.1"].sources == [DiscoverySource.ARP]


# --- nmap parsing ---------------------------------------------------------
def test_nmap_build_host_extracts_services_and_mac() -> None:
    info = {
        "addresses": {"ipv4": "192.168.0.10", "mac": "AA:BB:CC:00:11:22"},
        "tcp": {
            22: {"state": "open", "name": "ssh", "product": "OpenSSH", "version": "9.6p1"},
            80: {"state": "open", "name": "http", "product": "nginx", "version": "1.25"},
            3306: {"state": "closed", "name": "mysql", "product": "", "version": ""},
        },
    }
    host = _build_host("192.168.0.10", info)

    assert host.mac == "aa:bb:cc:00:11:22"
    assert host.sources == [DiscoverySource.NMAP]
    ports = {s.port for s in host.services}
    assert ports == {22, 80}  # closed port dropped
    ssh = next(s for s in host.services if s.port == 22)
    assert (ssh.product, ssh.version, ssh.source) == ("OpenSSH", "9.6p1", "nmap")
