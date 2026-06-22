"""Command-line interface.

Commands:
    scan             discover hosts/services/VMs, merge + persist inventory.json
    render           read inventory.json, write D2 diagrams + Markdown docs
    report           scan, then render (the common one-shot workflow)
    list             print a short text summary of a stored inventory
    validate-config  load + check a config file without scanning

A thin layer over the pipeline and renderers — no logic lives here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig, ConfigError
from .models import Inventory
from .pipeline import Orchestrator
from .render import D2Renderer, MarkdownRenderer
from .storage import JsonInventoryRepository


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="myinventory", description=__doc__)
    p.add_argument("--version", action="version", version=f"myinventory {__version__}")
    sub = p.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="discover and persist the inventory")
    scan.add_argument("-c", "--config", required=True)
    scan.add_argument("-o", "--out", default="./out")
    scan.set_defaults(func=_cmd_scan)

    render = sub.add_parser("render", help="render diagrams + docs from inventory.json")
    render.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    render.add_argument("-o", "--out", default="./out")
    render.set_defaults(func=_cmd_render)

    report = sub.add_parser("report", help="scan, then render (one shot)")
    report.add_argument("-c", "--config", required=True)
    report.add_argument("-o", "--out", default="./out")
    report.set_defaults(func=_cmd_report)

    lst = sub.add_parser("list", help="print a summary of a stored inventory")
    lst.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    lst.set_defaults(func=_cmd_list)

    val = sub.add_parser("validate-config", help="check a config file")
    val.add_argument("-c", "--config", required=True)
    val.set_defaults(func=_cmd_validate)

    return p


def _cmd_scan(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.config)
    inventory, report = Orchestrator(config).scan()
    repo = JsonInventoryRepository(Path(args.out) / "inventory.json")
    repo.save_merged(inventory)
    print(f"scan complete: {report}")
    for err in report.errors:
        print(f"  ! {err}", file=sys.stderr)
    print(f"saved -> {Path(args.out) / 'inventory.json'}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    inventory = Inventory.from_json(Path(args.inp).read_text())
    out = Path(args.out)
    d2_files = D2Renderer().render(inventory, out / "diagrams")
    md_files = MarkdownRenderer().render(inventory, out / "docs")
    print(f"rendered {len(d2_files)} D2 diagrams -> {out / 'diagrams'}")
    print(f"rendered {len(md_files)} Markdown files -> {out / 'docs'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    rc = _cmd_scan(args)
    if rc != 0:
        return rc
    args.inp = str(Path(args.out) / "inventory.json")
    return _cmd_render(args)


def _cmd_list(args: argparse.Namespace) -> int:
    inventory = Inventory.from_json(Path(args.inp).read_text())
    print(f"inventory generated {inventory.generated_at}")
    print(f"  networks: {len(inventory.networks)}")
    print(f"  hosts:    {len(inventory.hosts)}")
    print(f"  vms:      {len(inventory.vms)}")
    for host in sorted(inventory.hosts.values(), key=lambda h: h.primary_address or ""):
        label = host.hostname or host.primary_address or host.id
        svc = ", ".join(sorted({s.name or s.key for s in host.services}))
        print(f"  - {label:24} [{host.role.value}] {svc}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.config)
    print(
        f"config OK: {len(config.networks)} network(s), "
        f"{len(config.hypervisors)} hypervisor(s), "
        f"{len(config.linux_ssh)} linux_ssh target(s), "
        f"probes={config.service_probes}"
    )
    return 0
