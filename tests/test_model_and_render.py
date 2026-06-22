"""Smoke tests for the model round-trip, merge and both renderers.

These run without any network access — they exercise everything downstream of
discovery against the committed fixture inventory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myinventory.models import DiscoverySource, Host, HostRole, Inventory, Service
from myinventory.render import D2Renderer, MarkdownRenderer

FIXTURE = Path(__file__).parent / "fixtures" / "inventory.json"


@pytest.fixture()
def inventory() -> Inventory:
    return Inventory.from_json(FIXTURE.read_text())


def test_json_round_trip(inventory: Inventory) -> None:
    again = Inventory.from_json(inventory.to_json())
    assert again.to_dict() == inventory.to_dict()


def test_fixture_shape(inventory: Inventory) -> None:
    assert len(inventory.hosts) == 2
    assert len(inventory.vms) == 2
    hyper = inventory.hosts["ip:192.168.1.10"]
    assert hyper.is_hypervisor
    assert len(inventory.vms_of(hyper.id)) == 2


def test_host_id_priority() -> None:
    assert Host.compute_id(mac="AA-BB-CC-DD-EE-FF") == "mac:aa:bb:cc:dd:ee:ff"
    assert Host.compute_id(address="10.0.0.1") == "ip:10.0.0.1"
    assert Host.compute_id(hostname="Foo") == "host:foo"
    with pytest.raises(ValueError):
        Host.compute_id()


def test_upsert_merges_services() -> None:
    inv = Inventory()
    inv.upsert_host(
        Host(id="ip:1.1.1.1", addresses=["1.1.1.1"], sources=[DiscoverySource.TCP])
    )
    inv.upsert_host(
        Host(
            id="ip:1.1.1.1",
            addresses=["1.1.1.1"],
            hostname="late-name",
            role=HostRole.NAS,
            services=[Service(port=445, name="smb")],
        )
    )
    host = inv.hosts["ip:1.1.1.1"]
    assert host.hostname == "late-name"  # non-empty incoming wins
    assert host.role == HostRole.NAS
    assert len(host.services) == 1


def test_d2_renderer(tmp_path: Path, inventory: Inventory) -> None:
    files = D2Renderer().render(inventory, tmp_path)
    names = {f.name for f in files}
    assert "network.d2" in names
    assert "hypervisors.d2" in names
    text = (tmp_path / "hypervisors.d2").read_text()
    assert "web-1" in text and "db-1" in text  # both VMs nested under hypervisor


def test_markdown_renderer(tmp_path: Path, inventory: Inventory) -> None:
    MarkdownRenderer().render(inventory, tmp_path)
    assert (tmp_path / "index.md").exists()
    index = (tmp_path / "index.md").read_text()
    assert "Network Inventory" in index
    assert "pve-1" in index
    # one page per host
    pages = list((tmp_path / "hosts").glob("*.md"))
    assert len(pages) == len(inventory.hosts)
