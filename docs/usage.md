# Usage

## Install

```bash
# base install (model + renderers + tcp/banner reference backends)
pip install -e .

# with optional backends
pip install -e ".[scan]"   # icmp/arp sweeps, nmap probe
pip install -e ".[virt]"   # proxmox / vmware / libvirt
pip install -e ".[ssh]"    # authenticated SSH service probe
pip install -e ".[all]"    # everything
```

## Commands

```
myinventory scan             -c CONFIG [-o OUT]   discover + persist the inventory
myinventory render           [-i IN] [-o OUT]     write D2 diagrams + Markdown docs
myinventory report           -c CONFIG [-o OUT]   scan, then render (one shot)
myinventory list             [-i IN] [--stale N]  text summary of a stored inventory
myinventory diff             [-i IN] [--from ID] [--to ID] [A B] [--json]
myinventory validate-config  -c CONFIG            check a config without scanning
```

`scan` and `render` are split deliberately: `scan` touches the network and is
the slow/privileged step; `render` is a pure, instant transform you can run as
often as you like.

## Typical workflows

### First run

```bash
cp examples/inventory.example.yaml myinventory.yaml
$EDITOR myinventory.yaml
export PROXMOX_TOKEN=…              # referenced as env:PROXMOX_TOKEN
myinventory report -c myinventory.yaml -o ./out
d2 out/diagrams/network.d2 out/network.svg
```

### Re-scan and diff

Because IDs are stable and scans **merge**, re-running updates the same records.
Each scan is also snapshotted under `out/history/` (or the SQLite `snapshots`
table) *before* the merge, so change tracking can see removals and drift:

```bash
myinventory scan -c myinventory.yaml -o ./out
myinventory diff -o ./out            # what changed between the last two scans
git diff out/inventory.json          # or just eyeball the cumulative JSON
```

`diff` defaults to the two most recent snapshots; point it at specific ones with
`--from`/`--to` (snapshot ids, as listed under `out/history/`), at two arbitrary
JSON files (`myinventory diff a.json b.json`), or add `--json` for a machine-
readable diff. `render` turns the same snapshot history into a
[`changelog.md`](output-formats.md) page, newest scan first.

### Find hosts that have gone away

```bash
myinventory list -i ./out/inventory.json --stale 3
```

A host is **stale** when its stable ID is absent from each of the last N scans
(default 3) — useful for spotting decommissioned machines that linger in the
cumulative inventory.

### SQLite backend

Set `storage.backend: sqlite` in the config to persist to a single
`out/inventory.db` instead of `inventory.json` + `history/`. Every command works
the same; pass the `.db` path to `-i` for `render`/`list`/`diff`.

### Re-render only

```bash
myinventory render -i ./out/inventory.json -o ./site
```

## Scheduling (preview)

Until the built-in scheduler lands (roadmap M5), a cron/systemd timer works:

```cron
# every night at 02:00, scan and regenerate the docs
0 2 * * *  cd /opt/myinventory && PROXMOX_TOKEN=… .venv/bin/myinventory report -c myinventory.yaml -o /var/lib/myinventory/out
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | no command / usage error |
| 2 | config error (bad file, missing secret) |

Per-target failures during a scan are **not** fatal — they are printed to stderr
and recorded, and the scan still produces output for everything that worked.
