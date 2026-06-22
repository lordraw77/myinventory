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
myinventory scan             -c CONFIG [-o OUT]   discover + persist inventory.json
myinventory render           [-i IN] [-o OUT]     write D2 diagrams + Markdown docs
myinventory report           -c CONFIG [-o OUT]   scan, then render (one shot)
myinventory list             [-i IN]              text summary of a stored inventory
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

Because IDs are stable and scans **merge**, re-running updates the same records:

```bash
myinventory scan -c myinventory.yaml -o ./out
git diff out/inventory.json          # see exactly what changed
```

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
