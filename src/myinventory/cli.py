"""Command-line interface.

Commands:
    scan             discover hosts/services/VMs, merge + persist inventory
    render           read the inventory, write D2 diagrams + Markdown docs
    report           scan, then render (the common one-shot workflow)
    list             print a short text summary of a stored inventory
    diff             show what changed between two scans
    validate-config  load + check a config file without scanning

A thin layer over the pipeline, renderers and change-tracking helpers — no
domain logic lives here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import AppConfig, ConfigError
from .history import build_changelog, diff_inventories, render_diff_section, stale_hosts
from .logsetup import setup_logging
from .models import Inventory
from .pipeline import Orchestrator

log = logging.getLogger(__name__)
from .render import D2Renderer, MarkdownRenderer
from .storage import (
    InventoryRepository,
    JsonInventoryRepository,
    SqliteInventoryRepository,
    make_repository,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(getattr(args, "verbose", 0))
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

    # Shared options every subcommand accepts (e.g. `myinventory scan -v`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase log verbosity (-v for debug)",
    )

    sub = p.add_subparsers(dest="command")

    scan = sub.add_parser("scan", parents=[common], help="discover and persist the inventory")
    scan.add_argument("-c", "--config", required=True)
    scan.add_argument("-o", "--out", default="./out")
    scan.set_defaults(func=_cmd_scan)

    render = sub.add_parser(
        "render", parents=[common], help="render diagrams + docs from the inventory"
    )
    render.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    render.add_argument("-o", "--out", default="./out")
    render.set_defaults(func=_cmd_render)

    report = sub.add_parser("report", parents=[common], help="scan, then render (one shot)")
    report.add_argument("-c", "--config", required=True)
    report.add_argument("-o", "--out", default="./out")
    report.set_defaults(func=_cmd_report)

    lst = sub.add_parser("list", parents=[common], help="print a summary of a stored inventory")
    lst.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    lst.add_argument(
        "--stale",
        nargs="?",
        type=int,
        const=3,
        default=None,
        metavar="N",
        help="also list hosts not seen in the last N scans (default N=3)",
    )
    lst.set_defaults(func=_cmd_list)

    dif = sub.add_parser("diff", parents=[common], help="show what changed between two scans")
    dif.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    dif.add_argument("--from", dest="from_id", help="older snapshot id")
    dif.add_argument("--to", dest="to_id", help="newer snapshot id")
    dif.add_argument(
        "paths",
        nargs="*",
        help="two inventory JSON files to compare directly (instead of history)",
    )
    dif.add_argument("--json", action="store_true", help="emit the diff as JSON")
    dif.set_defaults(func=_cmd_diff)

    val = sub.add_parser("validate-config", parents=[common], help="check a config file")
    val.add_argument("-c", "--config", required=True)
    val.set_defaults(func=_cmd_validate)

    return p


def _repo_for(path: str | Path) -> InventoryRepository:
    """Pick a repository by file suffix: ``.db`` -> SQLite, else JSON."""
    p = Path(path)
    if p.suffix == ".db":
        return SqliteInventoryRepository(p)
    return JsonInventoryRepository(p)


def _cmd_scan(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.config)
    inventory, report = Orchestrator(config).scan()
    repo = make_repository(config.storage.backend, args.out)
    repo.save_merged(inventory, keep_history=config.storage.keep_history)
    log.info("persisted inventory -> %s (%s)", args.out, config.storage.backend)
    print(f"scan complete: {report}")
    for err in report.errors:
        print(f"  ! {err}", file=sys.stderr)
    print(f"saved -> {args.out} ({config.storage.backend})")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    repo = _repo_for(args.inp)
    inventory = repo.load()
    if inventory is None:
        print(f"no inventory found at {args.inp}", file=sys.stderr)
        return 1
    out = Path(args.out)
    log.info("rendering diagrams + docs to %s", out)
    changelog = build_changelog(repo.snapshots())
    d2_files = D2Renderer().render(inventory, out / "diagrams")
    md_files = MarkdownRenderer().render(inventory, out / "docs", changelog=changelog)
    log.info("rendered %d D2 diagram(s), %d Markdown file(s)", len(d2_files), len(md_files))
    print(f"rendered {len(d2_files)} D2 diagrams -> {out / 'diagrams'}")
    print(f"rendered {len(md_files)} Markdown files -> {out / 'docs'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.config)
    inventory, report = Orchestrator(config).scan()
    repo = make_repository(config.storage.backend, args.out)
    repo.save_merged(inventory, keep_history=config.storage.keep_history)
    log.info("persisted inventory -> %s (%s)", args.out, config.storage.backend)
    print(f"scan complete: {report}")
    for err in report.errors:
        print(f"  ! {err}", file=sys.stderr)

    merged = repo.load() or inventory
    out = Path(args.out)
    log.info("rendering diagrams + docs to %s", out)
    changelog = build_changelog(repo.snapshots())
    d2_files = D2Renderer().render(merged, out / "diagrams")
    md_files = MarkdownRenderer().render(merged, out / "docs", changelog=changelog)
    log.info("rendered %d D2 diagram(s), %d Markdown file(s)", len(d2_files), len(md_files))
    print(f"rendered {len(d2_files)} D2 diagrams -> {out / 'diagrams'}")
    print(f"rendered {len(md_files)} Markdown files -> {out / 'docs'}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    repo = _repo_for(args.inp)
    inventory = repo.load()
    if inventory is None:
        print(f"no inventory found at {args.inp}", file=sys.stderr)
        return 1
    print(f"inventory generated {inventory.generated_at}")
    print(f"  networks:   {len(inventory.networks)}")
    print(f"  hosts:      {len(inventory.hosts)}")
    print(f"  vms:        {len(inventory.vms)}")
    print(f"  containers: {sum(len(h.containers) for h in inventory.hosts.values())}")
    print(f"  packages:   {sum(len(h.packages) for h in inventory.hosts.values())}")
    for host in sorted(inventory.hosts.values(), key=lambda h: h.primary_address or ""):
        label = host.hostname or host.primary_address or host.id
        svc = ", ".join(sorted({s.name or s.key for s in host.services}))
        tags = f"  {{{', '.join(host.tags)}}}" if host.tags else ""
        print(f"  - {label:24} [{host.role.value}] {svc}{tags}")

    if args.stale is not None:
        snaps = [inv for _, inv in repo.snapshots()]
        stale = stale_hosts(inventory, snaps, scans=args.stale)
        print(f"\nstale (not seen in last {args.stale} scans): {len(stale)}")
        for s in stale:
            print(f"  - {s.label:24} last_seen={s.host.last_seen or '—'}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    if args.paths:
        if len(args.paths) != 2:
            print("diff expects exactly two file paths", file=sys.stderr)
            return 1
        old = Inventory.from_json(Path(args.paths[0]).read_text())
        new = Inventory.from_json(Path(args.paths[1]).read_text())
    else:
        repo = _repo_for(args.inp)
        ids = repo.snapshot_ids()
        if len(ids) < 2 and not (args.from_id and args.to_id):
            print("need at least two snapshots to diff", file=sys.stderr)
            return 1
        from_id = args.from_id or ids[-2]
        to_id = args.to_id or ids[-1]
        loaded_old = repo.load_snapshot(from_id)
        loaded_new = repo.load_snapshot(to_id)
        if loaded_old is None or loaded_new is None:
            print("snapshot not found", file=sys.stderr)
            return 1
        old, new = loaded_old, loaded_new

    result = diff_inventories(old, new)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_diff_section("diff", result))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    config = AppConfig.load(args.config)
    enr = config.enrichment
    passes = [
        name
        for name, on in (
            ("snmp", enr.snmp.enabled),
            ("hostname", enr.reverse_dns or bool(enr.dhcp_leases)),
            ("fingerprint", enr.os_fingerprint),
            ("classify", enr.classify),
        )
        if on
    ]
    print(
        f"config OK: {len(config.networks)} network(s), "
        f"{len(config.hypervisors)} hypervisor(s), "
        f"{len(config.linux_ssh)} linux_ssh target(s), "
        f"probes={config.service_probes}, "
        f"enrichment={passes or ['(none)']}, "
        f"rules={len(enr.rules)}, "
        f"storage={config.storage.backend}"
    )
    return 0
