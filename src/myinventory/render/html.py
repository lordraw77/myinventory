"""Render an :class:`Inventory` to a self-contained static HTML site (M6).

Where the Markdown renderer targets a wiki, this targets a browser: an
``index.html`` with the summary and subnet tables, a page per host, a shared
stylesheet and — when the ``d2`` CLI is installed — the network diagram compiled
to inline SVG and embedded on the index. With no ``d2`` binary the site still
builds; it just links to the ``.d2`` source instead of showing a picture.

Like the other renderers this is (almost) a pure function of the model. The one
side effect beyond writing files is the optional ``d2`` subprocess, which is
guarded and degrades gracefully.
"""

from __future__ import annotations

import html
import logging
import re
import shutil
import subprocess
from pathlib import Path

from ..models import Host, Inventory

log = logging.getLogger(__name__)

_STYLE = """\
:root { --fg:#1f2937; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; }
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       color: var(--fg); max-width: 980px; margin: 2rem auto; padding: 0 1rem;
       line-height: 1.5; }
h1, h2, h3 { line-height: 1.2; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
nav { margin-bottom: 1.5rem; font-size: .9rem; color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92rem; }
th, td { border: 1px solid var(--line); padding: .4rem .6rem; text-align: left; }
th { background: #f9fafb; }
code { background: #f3f4f6; padding: .1rem .3rem; border-radius: 4px; }
.muted { color: var(--muted); }
.diagram svg { max-width: 100%; height: auto; }
.summary td:last-child { text-align: right; }
footer { margin-top: 3rem; color: var(--muted); font-size: .85rem;
         border-top: 1px solid var(--line); padding-top: 1rem; }
"""


def _slug(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def _esc(value: object) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


class HtmlRenderer:
    def render(
        self,
        inventory: Inventory,
        out_dir: str | Path,
        *,
        diagrams_dir: str | Path | None = None,
        changelog_md: str | None = None,
        site: str | None = None,
    ) -> list[Path]:
        out = Path(out_dir)
        (out / "hosts").mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        written.append(self._write(out / "style.css", _STYLE))

        diagram_svg = self._network_svg(diagrams_dir, out) if diagrams_dir else None
        written.append(
            self._write(
                out / "index.html",
                self._index(inventory, diagram_svg=diagram_svg, site=site),
            )
        )
        for host in inventory.hosts.values():
            page = out / "hosts" / f"{_slug(host.id)}.html"
            written.append(self._write(page, self._host_page(inventory, host, site)))
        log.info("rendered static site -> %s (%d files)", out, len(written))
        return written

    # --- diagram embedding ------------------------------------------------
    def _network_svg(self, diagrams_dir: str | Path, out: Path) -> str | None:
        """Compile ``network.d2`` to inline SVG via the ``d2`` CLI, if present."""
        src = Path(diagrams_dir) / "network.d2"
        if not src.exists():
            return None
        d2 = shutil.which("d2")
        if d2 is None:
            log.info("d2 binary not found; site will link to D2 source instead")
            return None
        target = out / "network.svg"
        try:
            subprocess.run(  # noqa: S603
                [d2, str(src), str(target)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("d2 render failed: %s", exc)
            return None
        return target.read_text()

    # --- pages ------------------------------------------------------------
    def _index(
        self, inv: Inventory, *, diagram_svg: str | None, site: str | None
    ) -> str:
        title = f"Network Inventory — {site}" if site else "Network Inventory"
        body = [
            f"<h1>{html.escape(title)}</h1>",
            f'<p class="muted">Generated {_esc(inv.generated_at)}</p>',
        ]
        if diagram_svg:
            body += ['<div class="diagram">', diagram_svg, "</div>"]

        services = sum(len(h.services) for h in inv.hosts.values())
        containers = sum(len(h.containers) for h in inv.hosts.values())
        body += [
            "<h2>Summary</h2>",
            '<table class="summary">',
            "<tr><th>Metric</th><th>Count</th></tr>",
            f"<tr><td>Networks</td><td>{len(inv.networks)}</td></tr>",
            f"<tr><td>Hosts</td><td>{len(inv.hosts)}</td></tr>",
            f"<tr><td>Virtual machines</td><td>{len(inv.vms)}</td></tr>",
            f"<tr><td>Services</td><td>{services}</td></tr>",
            f"<tr><td>Containers</td><td>{containers}</td></tr>",
            "</table>",
        ]

        for net in inv.networks:
            body += [
                f"<h2>{_esc(net.label)} <code>{_esc(net.cidr)}</code></h2>",
                "<table><tr><th>Host</th><th>Address</th><th>Role</th><th>Services</th></tr>",
            ]
            for h in sorted(inv.hosts_in(net), key=lambda x: x.primary_address or ""):
                name = h.hostname or h.primary_address or h.id
                link = f'<a href="hosts/{_slug(h.id)}.html">{html.escape(name)}</a>'
                svc = ", ".join(sorted({s.name or s.key for s in h.services})) or "—"
                body.append(
                    f"<tr><td>{link}</td><td>{_esc(h.primary_address)}</td>"
                    f"<td>{_esc(h.role.value)}</td><td>{html.escape(svc)}</td></tr>"
                )
            body.append("</table>")

        return self._document(title, body, css_href="style.css")

    def _host_page(self, inv: Inventory, host: Host, site: str | None) -> str:
        title = host.hostname or host.primary_address or host.id
        body = [
            '<nav><a href="../index.html">&larr; Inventory</a></nav>',
            f"<h1>{html.escape(title)}</h1>",
            "<table>",
            f"<tr><th>ID</th><td><code>{_esc(host.id)}</code></td></tr>",
            f"<tr><th>Addresses</th><td>{_esc(', '.join(host.addresses))}</td></tr>",
            f"<tr><th>MAC</th><td>{_esc(host.mac)}</td></tr>",
            f"<tr><th>Role</th><td>{_esc(host.role.value)}</td></tr>",
            f"<tr><th>OS</th><td>{_esc(host.os)}</td></tr>",
            f"<tr><th>Vendor</th><td>{_esc(host.extra.get('vendor'))}</td></tr>",
            f"<tr><th>Tags</th><td>{_esc(', '.join(host.tags))}</td></tr>",
            f"<tr><th>First seen</th><td>{_esc(host.first_seen)}</td></tr>",
            f"<tr><th>Last seen</th><td>{_esc(host.last_seen)}</td></tr>",
            "</table>",
            "<h2>Services</h2>",
        ]
        if host.services:
            body.append(
                "<table><tr><th>Port</th><th>Proto</th><th>Service</th>"
                "<th>Product</th><th>Version</th></tr>"
            )
            for s in sorted(host.services, key=lambda x: x.port):
                body.append(
                    f"<tr><td>{s.port}</td><td>{_esc(s.protocol)}</td>"
                    f"<td>{_esc(s.name)}</td><td>{_esc(s.product)}</td>"
                    f"<td>{_esc(s.version)}</td></tr>"
                )
            body.append("</table>")
        else:
            body.append('<p class="muted">No services detected.</p>')

        if host.containers:
            body += ["<h2>Containers</h2>",
                     "<table><tr><th>Container</th><th>Image</th><th>State</th></tr>"]
            for c in sorted(host.containers, key=lambda x: x.name):
                body.append(
                    f"<tr><td>{_esc(c.name)}</td><td>{_esc(c.image)}</td>"
                    f"<td>{_esc(c.state)}</td></tr>"
                )
            body.append("</table>")

        return self._document(title, body, css_href="../style.css")

    # --- shell ------------------------------------------------------------
    @staticmethod
    def _document(title: str, body: list[str], *, css_href: str = "style.css") -> str:
        return (
            "<!doctype html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n"
            f'<link rel="stylesheet" href="{css_href}">\n'
            "</head>\n<body>\n"
            + "\n".join(body)
            + '\n<footer>Generated by myinventory.</footer>\n'
            "</body>\n</html>\n"
        )

    @staticmethod
    def _write(path: Path, content: str) -> Path:
        path.write_text(content)
        return path
