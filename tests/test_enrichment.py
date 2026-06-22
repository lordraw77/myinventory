"""Tests for Milestone 4 — enrichment & accuracy.

The enrichers are decoupled from the network the same way the rest of the suite
is: pure helpers (lease parsers, OS heuristics, OUI lookup, classification) are
tested directly, and the network-touching passes (reverse DNS, TTL probe, SNMP)
have their single I/O function monkeypatched so nothing hits the wire.
"""

from __future__ import annotations

import pytest

from myinventory.config import (
    AppConfig,
    ClassificationRule,
    EnrichmentConfig,
    SnmpConfig,
)
from myinventory.enrich import available
from myinventory.enrich import classify as classify_mod
from myinventory.enrich import dns as dns_mod
from myinventory.enrich import fingerprint as fp_mod
from myinventory.enrich import snmp as snmp_mod
from myinventory.enrich.classify import ClassifierEnricher, classify_host
from myinventory.enrich.dns import (
    HostnameEnricher,
    parse_dnsmasq_leases,
    parse_isc_leases,
)
from myinventory.enrich.fingerprint import (
    OsFingerprintEnricher,
    guess_os,
    initial_ttl,
)
from myinventory.enrich.oui import vendor_for_mac
from myinventory.enrich.snmp import SnmpEnricher, SnmpUnavailable, parse_sys_descr
from myinventory.models import Host, HostRole, Inventory, Service


# --- registry -------------------------------------------------------------
def test_all_enrichers_registered() -> None:
    assert set(available()) == {"snmp", "hostname", "fingerprint", "classify"}


def _inv(*hosts: Host) -> Inventory:
    inv = Inventory()
    for h in hosts:
        inv.hosts[h.id] = h
    return inv


# --- OUI ------------------------------------------------------------------
def test_vendor_for_mac_known_and_role_hint() -> None:
    vendor, role = vendor_for_mac("00:0C:29:AB:CD:EF")
    assert vendor == "VMware" and role == HostRole.VM
    vendor, role = vendor_for_mac("dc-2c-6e-11-22-33")  # dashes, upper
    assert vendor == "MikroTik" and role == HostRole.NETWORK


def test_vendor_for_mac_unknown() -> None:
    assert vendor_for_mac("ff:ff:ff:00:00:00") == (None, None)
    assert vendor_for_mac(None) == (None, None)
    assert vendor_for_mac("garbage") == (None, None)


# --- DHCP lease parsers ---------------------------------------------------
def test_parse_dnsmasq_leases() -> None:
    text = (
        "1700000000 aa:bb:cc:dd:ee:01 192.168.1.10 nas01 01:aa:bb:cc:dd:ee:01\n"
        "1700000001 aa:bb:cc:dd:ee:02 192.168.1.11 * 01:aa:bb:cc:dd:ee:02\n"
        "duid 00:01:00:01\n"  # non-lease line -> skipped
    )
    leases = parse_dnsmasq_leases(text)
    assert ("aa:bb:cc:dd:ee:01", "192.168.1.10", "nas01") in leases
    assert ("aa:bb:cc:dd:ee:02", "192.168.1.11", None) in leases


def test_parse_isc_leases_keeps_last_per_ip() -> None:
    text = """
lease 192.168.1.20 {
  hardware ethernet aa:bb:cc:dd:ee:03;
  client-hostname "old-name";
}
lease 192.168.1.20 {
  hardware ethernet aa:bb:cc:dd:ee:03;
  client-hostname "printer-2";
}
"""
    leases = parse_isc_leases(text)
    assert leases == [("aa:bb:cc:dd:ee:03", "192.168.1.20", "printer-2")]


# --- hostname enricher ----------------------------------------------------
def test_hostname_enricher_dhcp_then_rdns(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leases = tmp_path / "dnsmasq.leases"
    leases.write_text("1700000000 aa:bb:cc:dd:ee:01 192.168.1.10 nas01 *\n")

    h_dhcp = Host(id="ip:192.168.1.10", addresses=["192.168.1.10"],
                  mac="aa:bb:cc:dd:ee:01")
    h_rdns = Host(id="ip:192.168.1.50", addresses=["192.168.1.50"])
    h_named = Host(id="ip:192.168.1.99", addresses=["192.168.1.99"],
                   hostname="already")
    inv = _inv(h_dhcp, h_rdns, h_named)

    monkeypatch.setattr(
        dns_mod, "_reverse_lookup",
        lambda addr: "router.lan" if addr == "192.168.1.50" else None,
    )
    cfg = EnrichmentConfig(reverse_dns=True, dhcp_leases=[str(leases)])
    result = HostnameEnricher().enrich(inv, cfg)

    assert h_dhcp.hostname == "nas01"
    assert h_dhcp.extra["dhcp_hostname"] == "nas01"
    assert h_rdns.hostname == "router.lan"
    assert h_rdns.extra["rdns"] == "router.lan"
    assert h_named.hostname == "already"  # not overwritten
    assert result.applied == 2


def test_hostname_enricher_missing_lease_file_is_soft_error() -> None:
    inv = _inv(Host(id="ip:10.0.0.1", addresses=["10.0.0.1"]))
    cfg = EnrichmentConfig(reverse_dns=False, dhcp_leases=["/no/such/file.leases"])
    result = HostnameEnricher().enrich(inv, cfg)
    assert result.errors and "lease file" in result.errors[0]


# --- OS fingerprint -------------------------------------------------------
@pytest.mark.parametrize(
    ("observed", "expected"),
    [(58, 64), (118, 128), (245, 255), (300, None)],
)
def test_initial_ttl_rounds_up(observed: int, expected: int | None) -> None:
    assert initial_ttl(observed) == expected


def test_guess_os_snmp_wins() -> None:
    os_name, conf = guess_os(
        ttl=64, ports=set(), service_names=set(),
        snmp_descr="RouterOS RB5009 by MikroTik",
    )
    assert os_name == "RouterOS" and conf == "high"


def test_guess_os_windows_from_ports() -> None:
    os_name, conf = guess_os(ttl=128, ports={135, 445, 3389}, service_names={"rdp"})
    assert os_name == "Windows" and conf == "medium"


def test_guess_os_smb_alone_is_not_windows() -> None:
    # A Linux Samba / NAS box exposes 445 too — that alone must not say Windows.
    os_name, _ = guess_os(ttl=64, ports={445, 5000}, service_names={"smb", "http"})
    assert os_name == "Linux/Unix"


def test_guess_os_linux_from_ssh() -> None:
    os_name, _ = guess_os(ttl=64, ports={22, 80}, service_names={"ssh", "http"})
    assert os_name == "Linux/Unix"


def test_guess_os_none_without_signal() -> None:
    assert guess_os(ttl=None, ports=set(), service_names=set()) == (None, "low")


def test_fingerprint_enricher_sets_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fp_mod, "_probe_ttl", lambda addr, timeout=1.0: 64)
    host = Host(
        id="ip:10.0.0.5", addresses=["10.0.0.5"],
        services=[Service(port=22, name="ssh")],
    )
    inv = _inv(host)
    OsFingerprintEnricher().enrich(inv, EnrichmentConfig())
    assert host.os == "Linux/Unix"
    assert host.extra["os_fingerprint"]["ttl"] == 64
    assert host.extra["os_fingerprint"]["initial_ttl"] == 64


def test_fingerprint_does_not_override_known_os(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fp_mod, "_probe_ttl", lambda addr, timeout=1.0: 128)
    host = Host(id="ip:10.0.0.6", addresses=["10.0.0.6"], os="Ubuntu 22.04",
                services=[Service(port=22, name="ssh")])
    OsFingerprintEnricher().enrich(_inv(host), EnrichmentConfig())
    assert host.os == "Ubuntu 22.04"  # SSH-derived OS preserved


# --- SNMP -----------------------------------------------------------------
def test_parse_sys_descr_hints() -> None:
    hints = parse_sys_descr("Linux nas 5.15 Synology DSM")
    assert hints["vendor"] == "Synology" and hints["os"] == "Linux"


def test_snmp_enricher_disabled_is_noop() -> None:
    host = Host(id="ip:10.0.0.7", addresses=["10.0.0.7"])
    result = SnmpEnricher().enrich(_inv(host), EnrichmentConfig())
    assert result.applied == 0 and "snmp" not in host.extra


def test_snmp_enricher_applies_system_group(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query(addr, oids, **kw):
        if addr != "10.0.0.8":
            return None
        return {
            snmp_mod.OID_SYS_DESCR: "RouterOS RB5009 MikroTik",
            snmp_mod.OID_SYS_NAME: "gw-core",
            snmp_mod.OID_SYS_OBJECT_ID: "1.3.6.1.4.1.14988.1",
        }

    monkeypatch.setattr(snmp_mod, "_snmp_query", fake_query)
    host = Host(id="ip:10.0.0.8", addresses=["10.0.0.8"])
    miss = Host(id="ip:10.0.0.9", addresses=["10.0.0.9"])
    inv = _inv(host, miss)

    cfg = EnrichmentConfig(snmp=SnmpConfig(enabled=True, community="public"))
    result = SnmpEnricher().enrich(inv, cfg)

    assert result.applied == 1
    assert host.hostname == "gw-core"
    assert host.extra["snmp"]["descr"].startswith("RouterOS")
    assert host.extra["snmp_descr"].startswith("RouterOS")
    assert host.extra["snmp_vendor"] == "MikroTik"
    assert any(s.protocol == "udp" and s.port == 161 for s in host.services)
    assert "snmp" not in miss.extra


def test_snmp_enricher_reports_missing_pysnmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a, **k):
        raise SnmpUnavailable("no module named pysnmp")

    monkeypatch.setattr(snmp_mod, "_snmp_query", boom)
    host = Host(id="ip:10.0.0.10", addresses=["10.0.0.10"])
    cfg = EnrichmentConfig(snmp=SnmpConfig(enabled=True))
    result = SnmpEnricher().enrich(_inv(host), cfg)
    assert result.applied == 0
    assert result.errors and "pysnmp not installed" in result.errors[0]


# --- classification -------------------------------------------------------
def test_classify_web_and_db_tags() -> None:
    host = Host(
        id="ip:1.1.1.1",
        services=[Service(port=80, name="http"), Service(port=5432, name="postgresql")],
    )
    role, tags = classify_host(host)
    assert role is None  # a plain server gets tags, no special role
    assert "web-server" in tags and "database" in tags


def test_classify_printer_by_port() -> None:
    host = Host(id="ip:1.1.1.2", services=[Service(port=9100, name="jetdirect")])
    role, tags = classify_host(host)
    assert role == HostRole.PRINTER and "printer" in tags


def test_classify_nas_by_product() -> None:
    host = Host(
        id="ip:1.1.1.3",
        services=[Service(port=5000, name="http", product="Synology DSM")],
    )
    role, _ = classify_host(host)
    assert role == HostRole.NAS


def test_classify_network_from_vendor_hint() -> None:
    host = Host(id="ip:1.1.1.4")
    role, tags = classify_host(host, vendor="MikroTik", vendor_role=HostRole.NETWORK)
    assert role == HostRole.NETWORK
    assert "vendor:mikrotik" in tags


def test_classifier_enricher_keeps_proven_role_but_adds_tags() -> None:
    host = Host(
        id="ip:1.1.1.5", role=HostRole.VM,
        services=[Service(port=443, name="https")],
    )
    ClassifierEnricher().enrich(_inv(host), EnrichmentConfig())
    assert host.role == HostRole.VM  # proven role not downgraded
    assert "web-server" in host.tags


def test_classifier_enricher_sets_vendor_extra() -> None:
    host = Host(id="mac:00:11:32:aa:bb:cc", mac="00:11:32:aa:bb:cc")
    ClassifierEnricher().enrich(_inv(host), EnrichmentConfig())
    assert host.extra["vendor"] == "Synology"
    assert host.role == HostRole.NAS  # OUI role hint applied


def test_user_rule_overrides_role() -> None:
    host = Host(id="ip:1.1.1.6", hostname="cam-front",
                services=[Service(port=554, name="rtsp")])
    rule = ClassificationRule(
        role="network", tags=["camera"], hostname_regex=r"^cam-"
    )
    ClassifierEnricher().enrich(_inv(host), EnrichmentConfig(rules=[rule]))
    assert host.role == HostRole.NETWORK
    assert "camera" in host.tags


def test_empty_rule_matches_nothing() -> None:
    host = Host(id="ip:1.1.1.7")
    assert classify_mod._rule_matches(host, ClassificationRule(role="nas")) is False


# --- config ---------------------------------------------------------------
def test_enrichment_config_parsed(tmp_path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        """
enrichment:
  reverse_dns: false
  dhcp_leases: [/var/lib/misc/dnsmasq.leases]
  snmp:
    enabled: true
    community: private
    version: "2c"
  rules:
    - hostname_regex: "^printer-"
      role: printer
      tags: [office]
"""
    )
    enr = AppConfig.load(cfg).enrichment
    assert enr.reverse_dns is False
    assert enr.dhcp_leases == ["/var/lib/misc/dnsmasq.leases"]
    assert enr.snmp.enabled is True and enr.snmp.community == "private"
    assert enr.rules[0].role == "printer" and enr.rules[0].tags == ["office"]


def test_enrichment_defaults_when_absent(tmp_path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("networks:\n  - cidr: 10.0.0.0/24\n")
    enr = AppConfig.load(cfg).enrichment
    assert enr.reverse_dns and enr.os_fingerprint and enr.classify
    assert enr.snmp.enabled is False


def test_invalid_snmp_version_rejected(tmp_path) -> None:
    from myinventory.config import ConfigError

    cfg = tmp_path / "c.yaml"
    cfg.write_text("enrichment:\n  snmp:\n    version: '3'\n")
    with pytest.raises(ConfigError):
        AppConfig.load(cfg)
