# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses semantic
versioning.

## [Unreleased]

### Milestone 6 — Operability & polish (complete)

Exit criteria met: a locked, scheduled scan publishes an HTML site and notifies
on change, all from one config that can describe several sites. PyPI/`pipx`
publishing is intentionally deferred — install from source or the container
image.

#### Added
- **Lockfile** (`lock.py`): `scan`/`report` take an advisory, PID-stamped lock at
  `<out>/.myinventory.lock` so an overrunning scheduled run backs off (exit code
  3) instead of racing itself; a stale lock left by a dead process is reclaimed.
  `--no-lock` opts out.
- **Change notifications** (`notify/`): opt-in, stdlib-only webhook (Slack/JSON)
  and SMTP email channels. After a scan the diff against the previous snapshot is
  dispatched, best-effort; a failing channel is recorded, never fatal. Configured
  under `notifications:` (off by default).
- **HTML site** (`render/html.py`): `render --html` / `report --html` write a
  self-contained static site under `<out>/site/`, embedding the network diagram
  as SVG via the `d2` binary when present and degrading gracefully when absent.
- **Profiles / multiple sites**: `profiles:` overlays deep-merged over the base
  config, selected with `--profile`; a `site` label flows into HTML titles and
  notification subjects. `validate-config` lists profiles.
- **Container image** (`Dockerfile`) bundling all backends and `d2`, running
  unprivileged; systemd `service`/`timer` and cron recipes under `deploy/`.
- Docs: `operations.md` (scheduling, locking, notifications, HTML, profiles,
  Docker) and a `tutorial.md` walkthrough; configuration/usage/output-format
  updates.
- Tests for the lockfile, notification rendering + channels + dispatch gating,
  the HTML renderer, and profile/notification config parsing.

### Milestone 1 — Host & service discovery (complete)

Exit criteria met: `myinventory scan` on a real /24 yields hosts plus named
services and renders a usable map.

#### Added
- `icmp` discovery backend: ping-sweep via the system `ping` (no root, no deps).
- `arp` discovery backend: reads the kernel neighbour table (`ip neigh` with a
  `/proc/net/arp` fallback) to annotate local-segment hosts with their MAC.
- `nmap` discovery backend (optional, `[scan]` extra): host discovery plus
  service/version fingerprinting; degrades gracefully when the binary/module is
  absent.
- Service signatures rewritten with regex **version extraction** (`OpenSSH_9.6p1`
  → `9.6p1`, `nginx/1.25` → `1.25`) and an expanded port/banner table.
- Rate limiting (`rate_limit`) and per-target timeout (`target_timeout`) per
  network, applied through a shared, thread-pooled `sweep` helper.
- Tests: signature/version extraction, discovery backends, the sweep helper, and
  an in-process integration lab (real TCP service + banner probe).

#### Fixed
- Discovery backends now key hosts by **address** so `tcp`/`icmp`/`arp`/`nmap`
  results for the same machine merge into one record (the MAC from `arp` enriches
  it) instead of producing duplicates.
- Config loading no longer crashes when YAML parses a bare numeric password as an
  `int`: any non-string scalar secret is coerced to `str`.

### Milestone 0 — Foundations (complete)

Exit criteria met: `myinventory render --in fixtures/inventory.json` produces
valid D2 diagrams and Markdown documentation.

### Added
- Project scaffold, packaging (`pyproject.toml`), lint/type/test config.
- Full documentation set: architecture, roadmap, data model, configuration,
  discovery, output formats, usage, security, contributing, and ADRs 0001–0004.
- Core data model: `Host`, `Service`, `VirtualMachine`, `Network`, `Inventory`
  with stable IDs, field-level merge and JSON (de)serialization.
- Plugin registries + ABCs for discovery, service probes and virtualization.
- Reference backends: `tcp` host discovery, `banner` service probe, `proxmox`
  virtualization (collection logic wired, pending live test target).
- Pipeline orchestrator with discovery → service → virtualization → correlation
  stages and fail-soft error collection.
- JSON inventory repository with scan-over-scan merge.
- D2 renderer (network / subnet / hypervisor diagrams) and Markdown renderer
  (index + per-host pages).
- CLI: `scan`, `render`, `report`, `list`, `validate-config`.
- Sample `fixtures/inventory.json` so the renderers can be demoed without
  scanning a live network.
- `py.typed` marker so downstream consumers get the package's type hints.
- Test suite covering model round-trip, merge, the storage repository and both
  renderers.
