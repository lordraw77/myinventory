"""Tests for the HTML static-site renderer (M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myinventory.models import Host, HostRole, Inventory, Network, Service
from myinventory.render import HtmlRenderer


def _inventory() -> Inventory:
    inv = Inventory()
    inv.add_network(Network(cidr="10.0.0.0/24", name="lan"))
    inv.upsert_host(
        Host(
            id="ip:10.0.0.5",
            addresses=["10.0.0.5"],
            hostname="web",
            role=HostRole.PHYSICAL,
            services=[Service(port=80, name="http", product="nginx", version="1.25")],
        )
    )
    return inv


def test_render_writes_site_files(tmp_path: Path) -> None:
    files = HtmlRenderer().render(_inventory(), tmp_path, site="home")
    names = {p.name for p in files}
    assert "index.html" in names
    assert "style.css" in names
    assert (tmp_path / "hosts" / "ip-10-0-0-5.html").exists()

    index = (tmp_path / "index.html").read_text()
    assert "Network Inventory — home" in index
    assert 'href="hosts/ip-10-0-0-5.html"' in index

    page = (tmp_path / "hosts" / "ip-10-0-0-5.html").read_text()
    assert "web" in page
    assert "nginx" in page
    assert 'href="../style.css"' in page


def test_render_escapes_html(tmp_path: Path) -> None:
    inv = Inventory()
    inv.upsert_host(Host(id="ip:1.1.1.1", addresses=["1.1.1.1"], hostname="<x>&y"))
    HtmlRenderer().render(inv, tmp_path)
    page = (tmp_path / "hosts" / "ip-1-1-1-1.html").read_text()
    assert "<x>&y" not in page
    assert "&lt;x&gt;&amp;y" in page


def test_render_without_d2_binary_still_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When no d2 binary is available, the site builds without an embedded SVG.
    import myinventory.render.html as html_mod

    monkeypatch.setattr(html_mod.shutil, "which", lambda _name: None)  # type: ignore[attr-defined]
    diagrams = tmp_path / "diagrams"
    diagrams.mkdir()
    (diagrams / "network.d2").write_text("x: y\n")
    HtmlRenderer().render(_inventory(), tmp_path / "site", diagrams_dir=diagrams)
    assert (tmp_path / "site" / "index.html").exists()
    assert not (tmp_path / "site" / "network.svg").exists()
