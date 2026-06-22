# Tutorial — from zero to a published map

A 10-minute walkthrough that takes a fresh checkout to a scanned LAN, an HTML
site and a scheduled, notifying scan. It assumes a homelab `/24` with maybe a
Proxmox node and a Linux server; adapt the addresses.

## 1. Install

```bash
git clone https://github.com/lordraw77/myinventory
cd myinventory
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]"        # or pick extras: .[scan], .[virt], .[ssh], .[snmp]
```

Optionally install [`d2`](https://d2lang.com/tour/install) so the HTML site gets
an embedded network diagram.

## 2. Write a config

```bash
cp examples/inventory.example.yaml myinventory.yaml
$EDITOR myinventory.yaml
```

Start small — just one network with the dependency-free `tcp` discovery:

```yaml
site: home-lab
networks:
  - name: lan
    cidr: 192.168.1.0/24
    discovery: [tcp]
service_probes: [banner]
storage:
  backend: json
```

Check it without touching the network:

```bash
myinventory validate-config -c myinventory.yaml
```

## 3. First scan + render

```bash
myinventory report -c myinventory.yaml -o ./out
```

`report` scans, persists `out/inventory.json` (snapshotting it under
`out/history/` first), then renders D2 diagrams and Markdown docs. Look at what
it found:

```bash
myinventory list -i ./out/inventory.json
```

## 4. Add depth

Now wire in the things that make the map rich — edit `myinventory.yaml`:

```yaml
hypervisors:
  - name: pve
    type: proxmox
    host: 192.168.1.10
    username: root@pam
    token_name: myinventory
    secret: env:PROXMOX_TOKEN     # never inline a secret
    verify_tls: false

linux_ssh:
  - name: app
    host: 192.168.1.20
    username: ops
    key_file: ~/.ssh/id_ed25519
    sudo: true
```

```bash
export PROXMOX_TOKEN=...
myinventory report -c myinventory.yaml -o ./out
```

The map now nests VMs under their hypervisor and containers under their Docker
host, and each Linux host page lists packages, processes and containers.

## 5. Publish an HTML site

```bash
myinventory render -i ./out/inventory.json -o ./out --html
python -m http.server -d ./out/site 8080      # open http://localhost:8080
```

With `d2` installed the index shows the network diagram; otherwise it's tables
and per-host pages. Copy `out/site/` anywhere static files are served.

## 6. Track change over time

Re-run after something changes on the LAN and see exactly what moved:

```bash
myinventory scan -c myinventory.yaml -o ./out
myinventory diff -o ./out                      # last two snapshots
myinventory list -i ./out/inventory.json --stale 3   # hosts gone for 3 scans
```

`render` also writes `out/docs/changelog.md`, newest scan first.

## 7. Get notified

Add an opt-in `notifications` block so a change pings you (see
[configuration.md](configuration.md#notifications)):

```yaml
notifications:
  enabled: true
  webhooks:
    - url: https://hooks.slack.com/services/XXX/YYY/ZZZ
      format: slack
```

Now every `scan`/`report` that changes the inventory posts a summary. The first
scan against an empty history stays quiet.

## 8. Run it on a schedule

Install the systemd timer (nightly `report --html`):

```bash
sudo cp deploy/myinventory.service deploy/myinventory.timer /etc/systemd/system/
sudo mkdir -p /etc/myinventory /var/lib/myinventory
sudo cp myinventory.yaml /etc/myinventory/config.yaml
sudo install -m600 /dev/stdin /etc/myinventory/secrets.env <<'EOF'
PROXMOX_TOKEN=...
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now myinventory.timer
```

The CLI's lockfile means an overrun never stacks two scans. That's the whole
loop: scan → track → publish → notify, on a timer. See
[operations.md](operations.md) for cron, Docker and multi-site profiles.
