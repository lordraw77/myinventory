"""Render an :class:`Inventory` to Markdown documentation.

Produces:

* ``index.md``        — summary, subnet tables, hypervisor/VM overview.
* ``hosts/<id>.md``   — one page per host with its services and relationships.

Pure function of the model; suitable for committing to a wiki or feeding a
static-site generator.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Host, Inventory


def _slug(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


class MarkdownRenderer:
    def render(self, inventory: Inventory, out_dir: str | Path) -> list[Path]:
        out = Path(out_dir)
        (out / "hosts").mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        written.append(self._write(out / "index.md", self._index(inventory)))
        for host in inventory.hosts.values():
            page = out / "hosts" / f"{_slug(host.id)}.md"
            written.append(self._write(page, self._host_page(inventory, host)))
        return written

    # --- index ------------------------------------------------------------
    def _index(self, inv: Inventory) -> str:
        lines = [
            "# Network Inventory",
            "",
            f"_Generated: {inv.generated_at}_",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "| --- | ---: |",
            f"| Networks | {len(inv.networks)} |",
            f"| Hosts | {len(inv.hosts)} |",
            f"| Virtual machines | {len(inv.vms)} |",
            f"| Services | {sum(len(h.services) for h in inv.hosts.values())} |",
            f"| Containers | {sum(len(h.containers) for h in inv.hosts.values())} |",
            f"| Packages | {sum(len(h.packages) for h in inv.hosts.values())} |",
            "",
        ]

        for net in inv.networks:
            hosts = inv.hosts_in(net)
            lines += [
                f"## {net.label} (`{net.cidr}`)",
                "",
                "| Host | Address | Role | Services |",
                "| --- | --- | --- | --- |",
            ]
            for h in sorted(hosts, key=lambda x: x.primary_address or ""):
                name = h.hostname or "—"
                link = f"[{name}](hosts/{_slug(h.id)}.md)"
                svc = ", ".join(sorted({s.name or s.key for s in h.services})) or "—"
                lines.append(
                    f"| {link} | {h.primary_address or '—'} | {h.role.value} | {svc} |"
                )
            lines.append("")

        hypervisors = [h for h in inv.hosts.values() if h.is_hypervisor]
        if hypervisors:
            lines += ["## Virtualization", ""]
            for hyper in hypervisors:
                label = hyper.hostname or hyper.primary_address or hyper.id
                lines += [
                    f"### {label}",
                    "",
                    "| VM | State | vCPU | RAM (MB) | Guest OS |",
                    "| --- | --- | ---: | ---: | --- |",
                ]
                for vm in inv.vms_of(hyper.id):
                    lines.append(
                        f"| {vm.name} | {vm.power_state.value} | "
                        f"{vm.vcpus or '—'} | {vm.memory_mb or '—'} | "
                        f"{vm.guest_os or '—'} |"
                    )
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    # --- host page --------------------------------------------------------
    def _host_page(self, inv: Inventory, host: Host) -> str:
        title = host.hostname or host.primary_address or host.id
        lines = [
            f"# {title}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| ID | `{host.id}` |",
            f"| Addresses | {', '.join(host.addresses) or '—'} |",
            f"| MAC | {host.mac or '—'} |",
            f"| Role | {host.role.value} |",
            f"| OS | {host.os or '—'} |",
            f"| Kernel | {host.extra.get('kernel_release') or '—'} |",
            f"| Arch | {host.extra.get('arch') or '—'} |",
            f"| Uptime | {host.extra.get('uptime') or '—'} |",
            f"| Virtualization | {host.extra.get('virt') or '—'} |",
            f"| Tags | {', '.join(host.tags) or '—'} |",
            f"| First seen | {host.first_seen or '—'} |",
            f"| Last seen | {host.last_seen or '—'} |",
            "",
            "## Services",
            "",
        ]
        if host.services:
            lines += ["| Port | Proto | Service | Product | Version |",
                      "| ---: | --- | --- | --- | --- |"]
            for s in sorted(host.services, key=lambda x: x.port):
                lines.append(
                    f"| {s.port} | {s.protocol} | {s.name or '—'} | "
                    f"{s.product or '—'} | {s.version or '—'} |"
                )
        else:
            lines.append("_No services detected._")
        lines.append("")

        vms = inv.vms_of(host.id)
        if vms:
            lines += ["## Hosted virtual machines", "",
                      "| VM | State | vCPU | RAM (MB) |",
                      "| --- | --- | ---: | ---: |"]
            for vm in vms:
                lines.append(
                    f"| {vm.name} | {vm.power_state.value} | "
                    f"{vm.vcpus or '—'} | {vm.memory_mb or '—'} |"
                )
            lines.append("")

        if host.hypervisor_id:
            hv = inv.hosts.get(host.hypervisor_id)
            if hv is not None:
                label = hv.hostname or hv.primary_address or hv.id
                lines += [
                    "## Virtualization",
                    "",
                    f"Runs on hypervisor [{label}](./{_slug(hv.id)}.md).",
                    "",
                ]

        lines += self._containers_section(host)
        lines += self._packages_section(host)
        lines += self._processes_section(host)

        return "\n".join(lines).rstrip() + "\n"

    # --- deep-inspection sections (M3) ------------------------------------
    @staticmethod
    def _containers_section(host: Host) -> list[str]:
        if not host.containers:
            return []
        lines = ["## Containers", "",
                 "| Container | Image | State | Ports | Project |",
                 "| --- | --- | --- | --- | --- |"]
        for c in sorted(host.containers, key=lambda x: x.name):
            ports = ", ".join(c.ports) or "—"
            lines.append(
                f"| {c.name} | {c.image or '—'} | {c.state or '—'} | "
                f"{ports} | {c.compose_project or '—'} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _packages_section(host: Host) -> list[str]:
        if not host.packages:
            return []
        lines = [f"## Packages ({len(host.packages)})", "",
                 "| Package | Version | Manager |",
                 "| --- | --- | --- |"]
        for p in sorted(host.packages, key=lambda x: x.name.lower()):
            lines.append(f"| {p.name} | {p.version or '—'} | {p.manager} |")
        lines.append("")
        return lines

    @staticmethod
    def _processes_section(host: Host) -> list[str]:
        if not host.processes:
            return []
        lines = ["## Top processes", "",
                 "| PID | User | %CPU | RSS (KB) | Command | Listening |",
                 "| ---: | --- | ---: | ---: | --- | --- |"]
        for p in host.processes:
            ports = ", ".join(str(x) for x in p.listening_ports) or "—"
            lines.append(
                f"| {p.pid} | {p.user or '—'} | {p.cpu_percent if p.cpu_percent is not None else '—'} | "
                f"{p.rss_kb if p.rss_kb is not None else '—'} | {p.name} | {ports} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _write(path: Path, content: str) -> Path:
        path.write_text(content)
        return path
