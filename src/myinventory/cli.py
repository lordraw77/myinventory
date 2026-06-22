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
from .lock import FileLock, LockError
from .logsetup import setup_logging
from .models import Inventory
from .notify import dispatch_change
from .pipeline import Orchestrator
from .render import D2Renderer, HtmlRenderer, MarkdownRenderer
from .storage import (
    InventoryRepository,
    JsonInventoryRepository,
    SqliteInventoryRepository,
    make_repository,
)

log = logging.getLogger(__name__)


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
    except LockError as exc:
        print(f"lock error: {exc}", file=sys.stderr)
        return 3


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

    # Options shared by the scanning commands (scan, report).
    def _add_scan_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-c", "--config", required=True)
        sp.add_argument("-o", "--out", default="./out")
        sp.add_argument(
            "-p", "--profile", default=None, help="select a named config profile"
        )
        sp.add_argument(
            "--no-lock",
            action="store_true",
            help="skip the concurrency lockfile (not recommended for scheduled runs)",
        )

    scan = sub.add_parser("scan", parents=[common], help="discover and persist the inventory")
    _add_scan_opts(scan)
    scan.set_defaults(func=_cmd_scan)

    render = sub.add_parser(
        "render", parents=[common], help="render diagrams + docs from the inventory"
    )
    render.add_argument("-i", "--in", dest="inp", default="./out/inventory.json")
    render.add_argument("-o", "--out", default="./out")
    render.add_argument(
        "--html", action="store_true", help="also render a static HTML site"
    )
    render.set_defaults(func=_cmd_render)

    report = sub.add_parser("report", parents=[common], help="scan, then render (one shot)")
    _add_scan_opts(report)
    report.add_argument(
        "--html", action="store_true", help="also render a static HTML site"
    )
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
    val.add_argument("-p", "--profile", default=None, help="validate a named profile")
    val.set_defaults(func=_cmd_validate)

    return p


def _repo_for(path: str | Path) -> InventoryRepository:
    """Pick a repository by file suffix: ``.db`` -> SQLite, else JSON."""
    p = Path(path)
    if p.suffix == ".db":
        return SqliteInventoryRepository(p)
    return JsonInventoryRepository(p)


def _scan_and_persist(
    args: argparse.Namespace,
) -> tuple[AppConfig, InventoryRepository, Inventory]:
    """Shared scan path for ``scan``/``report``: lock, scan, persist, notify."""
    config = AppConfig.load(args.config, profile=getattr(args, "profile", None))
    with _lock(args):
        inventory, report = Orchestrator(config).scan()
        repo = make_repository(config.storage.backend, args.out)
        repo.save_merged(inventory, keep_history=config.storage.keep_history)
        log.info("persisted inventory -> %s (%s)", args.out, config.storage.backend)
        print(f"scan complete: {report}")
        for err in report.errors:
            print(f"  ! {err}", file=sys.stderr)
        for err in _notify(config, repo):
            print(f"  ! {err}", file=sys.stderr)
    return config, repo, inventory


def _lock(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    """Return the scan lock context, or a no-op when ``--no-lock`` is set."""
    if getattr(args, "no_lock", False):
        from contextlib import nullcontext

        return nullcontext()
    return FileLock(Path(args.out) / ".myinventory.lock")


def _notify(config: AppConfig, repo: InventoryRepository) -> list[str]:
    """Dispatch change notifications by diffing the last two snapshots."""
    if not config.notifications.enabled:
        return []
    ids = repo.snapshot_ids()
    if len(ids) < 2:
        return []  # first scan: nothing to compare against yet
    old = repo.load_snapshot(ids[-2])
    new = repo.load_snapshot(ids[-1])
    if old is None or new is None:
        return []
    diff = diff_inventories(old, new)
    return dispatch_change(config.notifications, diff, site=config.site)


def _cmd_scan(args: argparse.Namespace) -> int:
    config, _, _ = _scan_and_persist(args)
    print(f"saved -> {args.out} ({config.storage.backend})")
    return 0


def _render_all(
    inventory: Inventory,
    repo: InventoryRepository,
    out: Path,
    *,
    html: bool,
    site: str | None,
) -> None:
    """Render D2 + Markdown (+ optional HTML) and print a one-line summary each."""
    log.info("rendering diagrams + docs to %s", out)
    changelog = build_changelog(repo.snapshots())
    d2_files = D2Renderer().render(inventory, out / "diagrams")
    md_files = MarkdownRenderer().render(inventory, out / "docs", changelog=changelog)
    log.info("rendered %d D2 diagram(s), %d Markdown file(s)", len(d2_files), len(md_files))
    print(f"rendered {len(d2_files)} D2 diagrams -> {out / 'diagrams'}")
    print(f"rendered {len(md_files)} Markdown files -> {out / 'docs'}")
    if html:
        html_files = HtmlRenderer().render(
            inventory,
            out / "site",
            diagrams_dir=out / "diagrams",
            changelog_md=changelog,
            site=site,
        )
        print(f"rendered {len(html_files)} HTML files -> {out / 'site'}")


def _cmd_render(args: argparse.Namespace) -> int:
    repo = _repo_for(args.inp)
    inventory = repo.load()
    if inventory is None:
        print(f"no inventory found at {args.inp}", file=sys.stderr)
        return 1
    _render_all(inventory, repo, Path(args.out), html=args.html, site=None)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    config, repo, inventory = _scan_and_persist(args)
    merged = repo.load() or inventory
    _render_all(merged, repo, Path(args.out), html=args.html, site=config.site)
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
    profiles = AppConfig.profile_names(args.config)
    config = AppConfig.load(args.config, profile=args.profile)
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
    notif = config.notifications
    channels = (
        ["(disabled)"]
        if not notif.enabled
        else [
            *(["webhook"] * len(notif.webhooks)),
            *(["email"] if notif.email else []),
        ]
        or ["(no channels)"]
    )
    print(
        f"config OK: {len(config.networks)} network(s), "
        f"{len(config.hypervisors)} hypervisor(s), "
        f"{len(config.linux_ssh)} linux_ssh target(s), "
        f"probes={config.service_probes}, "
        f"enrichment={passes or ['(none)']}, "
        f"rules={len(enr.rules)}, "
        f"storage={config.storage.backend}, "
        f"notifications={channels}, "
        f"site={config.site or '(none)'}, "
        f"profiles={profiles or ['(none)']}"
    )
    return 0
