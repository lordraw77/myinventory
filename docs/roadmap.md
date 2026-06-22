# Roadmap

The roadmap is organized into milestones. Each milestone is independently
useful — you get value before the next one lands. Checkboxes track status.

Legend: ☐ todo · ◐ in progress · ☑ done

---

## Milestone 0 — Foundations (`v0.1`) ☑

Scaffold, data model, contracts and docs. No live scanning yet, but the model
and renderers are real and testable against fixtures.

- ☑ Project skeleton, `pyproject.toml`, packaging, lint/type/test config.
- ☑ Documentation set (architecture, roadmap, data model, configuration…).
- ☑ Core data model (`Host`, `Service`, `VirtualMachine`, `Network`, `Inventory`)
  with JSON (de)serialization.
- ☑ Plugin registries and abstract base classes for discovery / services /
  virtualization.
- ☑ Storage repository: persist + merge by stable ID.
- ☑ D2 renderer (network map, subnet maps, hypervisor→VM map).
- ☑ Markdown renderer (index + per-host pages + tables).
- ☑ CLI skeleton (`scan`, `render`, `report`, `validate-config`) wired to a
  fixture inventory.
- ☑ Unit tests for model round-trip, merge, and both renderers.

**Exit criteria:** `myinventory render --in fixtures/inventory.json` produces
valid D2 + Markdown.

---

## Milestone 1 — Host & service discovery (`v0.2`) ☑

Make the scan real on a LAN.

- ☑ ICMP ping-sweep discovery backend.
- ☑ ARP-scan discovery backend (local segment).
- ☑ TCP-connect discovery backend (firewall-friendly).
- ☑ Port scanner + banner grabber.
- ☑ Service signature table (ssh, http/https, postgres, mysql, redis, smb,
  rdp, dns, snmp, …) with version extraction.
- ☑ Optional `nmap` backend (used when the binary is present).
- ☑ Orchestrator: thread pool, per-target timeout, rate limiting, error
  collection.
- ☑ Integration test against fake services (in-process TCP lab; a
  docker-compose variant remains a future nicety).

**Exit criteria:** `myinventory scan` on a real /24 yields hosts + named
services and renders a usable map.

---

## Milestone 2 — Virtualization (`v0.3`) — *headline feature* ☑

Enumerate VMs and link them to their hypervisor.

- ☑ `VirtualizationBackend` lifecycle finalized (connect → collect → close).
- ☑ Proxmox VE backend (`proxmoxer`): nodes, VMs/LXC, status, resources, IPs.
- ☑ libvirt backend (KVM/QEMU): domains, state, resources, guest IPs via agent.
- ☑ VMware backend (`pyvmomi`): vCenter + standalone ESXi, VMs, resource pools.
- ☑ Correlation: VM IPs ↔ discovered hosts; hypervisor mgmt IP ↔ host node.
- ☑ D2 hypervisor map showing host containers with nested VM nodes.

**Exit criteria:** a Proxmox/ESXi node in config produces a map where the host
box contains its running VMs, cross-linked to network discovery.

---

## Milestone 3 — Agentless Linux deep inspection over SSH (`v0.4`) ☑

Go beyond "a port is open": log into Linux servers read-only over SSH and
inventory what actually runs on them — installed software, running processes and
Docker workloads. Still agentless: a short-lived SSH session running read-only
commands, no software left behind.

- ☑ Config surface: a `linux_ssh` target block — `username`, `password`,
  `key_file`, `sudo`, `sudo_password`, `port` — with every secret resolved via
  the `env:`/`file:` reference scheme. *(landed early)*
- ☑ SSH transport layer (paramiko): connect using SSH key/agent and/or
  username+password auth, run privileged commands via `sudo -S` fed the
  configured `sudo_password` (or passwordless sudo), honor `~/.ssh/config`,
  bastion/jump-host support (`ProxyCommand`), strict host-key checking,
  per-host timeout.
- ☑ Base OS facts: distro + version (`/etc/os-release`), kernel (`uname`),
  architecture, uptime, virtualization hint (`systemd-detect-virt`).
- ☑ **Installed software**: package inventory across managers — `dpkg`/`apt`
  (Debian/Ubuntu), `rpm`/`dnf` (RHEL/Fedora/Rocky), plus `snap`/`flatpak`
  when present. Normalized to `(name, version, manager)`.
- ☑ **Running processes & listening sockets**: `ss -tulpn` → map each listening
  port to its owning process/unit, enriching the `Service` records from network
  discovery with the real binary and PID. Top processes by CPU/RSS.
- ☑ **systemd services**: enabled/running units (`systemctl list-units`) so the
  inventory reflects intended services, not just currently-open ports.
- ☑ **Docker / container runtime discovery**:
  - Detect the runtime (docker / podman) and its version.
  - Enumerate containers (`docker ps -a` / `podman ps -a`): name, image + tag,
    state, ports published to the host, mounts, restart policy, compose
    project/labels.
  - Map published container ports back to the host's network-discovered
    services (so "host:8080 → nginx" links to "container web-1 → nginx:1.25").
  - *(Local images/networks/volumes enumeration deferred — backlog.)*
- ☑ Data model: added `Package`, `Process`, and `Container` records (containers
  render as nodes nested under their host, the way a VM nests under its
  hypervisor; `HostRole.CONTAINER` styles them).
- ☑ Rendering: container nodes nested under their Docker host in D2
  (`containers.d2`, mirroring the hypervisor→VM view); per-host Markdown gains
  **Packages**, **Processes** and **Containers** sections.
- ☑ Safety: read-only command allow-list, `sudo` strictly opt-in (off unless
  configured) and used only for the commands that require it (sockets, runtime),
  graceful degradation when a command is missing.
- ☑ Integration test against a fake runner (in-process stand-in for the
  docker-compose lab) asserting containers + packages are discovered.

**Exit criteria:** pointing `myinventory` at a Linux host with Docker yields its
OS, installed packages, running services and a list of containers — rendered in
both the D2 map and the host's Markdown page.

---

## Milestone 4 — Enrichment & accuracy (`v0.5`) ☑

Turn discovered addresses into *identified* hosts. A post-correlation enrichment
stage ([`enrich/`](../src/myinventory/enrich/)) runs a fixed pipeline —
`snmp → hostname → fingerprint → classify` — over the merged inventory, each pass
an `Enricher` plugin that annotates in place and fails soft. See
[enrichment.md](enrichment.md).

- ☑ SNMP probe for network appliances (switches, APs, NAS): polls the `system`
  group (`sysDescr`/`sysName`/`sysObjectID`…), names the host, seeds the OS guess
  and role. Opt-in, needs the `[snmp]` extra; `pysnmp` imported lazily and
  degrades to a single note when absent.
- ☑ OS fingerprint heuristics (TTL, banner, open-port profile) combined
  most-trusted-first into an `os_fingerprint` guess that never overrides an
  SSH/SNMP-derived OS.
- ☑ Reverse-DNS and DHCP-lease hostname resolution (dnsmasq + ISC lease parsers),
  neither overwriting a stronger source's name.
- ☑ Tagging/classification rules: built-in heuristics (services + OS + SNMP + MAC
  OUI vendor) assign role/tags without downgrading a proven role, plus declarative
  user `rules` that run last and may override.
- ☑ Unit tests for every pass (pure helpers tested directly; the network-touching
  passes monkeypatch their single I/O function).

**Exit criteria:** a scan over a mixed LAN names IP-only hosts, guesses their OS,
and classes switches/NAS/printers by role + tags — visible in `list`, the D2 maps
and the per-host Markdown.

---

## Milestone 5 — Change tracking & reporting (`v0.6`) ☑

Turn a one-off census into a tracked one. Every scan is snapshotted *before* it
is merged into the cumulative `inventory.json`, so the history records exactly
what each scan saw — which is what makes removals and drift detectable (the
merged state never drops a host). The change-tracking helpers live in
[`history/`](../src/myinventory/history/) and are pure functions of the model.

- ☑ History: keep prior scans (raw per-scan snapshots) behind the repository
  interface; compute a structured diff between two inventories
  ([`history/diff.py`](../src/myinventory/history/diff.py)).
- ☑ `myinventory diff` command — new/removed hosts, changed fields/services and
  drifted VMs; compares the last two snapshots, two named snapshots
  (`--from`/`--to`) or two JSON files, with a `--json` machine form.
- ☑ Markdown changelog page (`docs/changelog.md`): the diff history newest-first,
  one section per scan, linked from `index.md`.
- ☑ Optional SQLite backend (`SqliteInventoryRepository`) behind the existing
  repository interface; selected via `storage.backend: sqlite`.
- ☑ "Stale host" detection — hosts absent from the last N scans, surfaced by
  `myinventory list --stale N` (`history/stale.py`).

**Exit criteria:** re-scanning a changed LAN yields a `diff` of what moved, a
changelog page per scan, and a `list --stale` flag for hosts that have gone away —
with the same data available from either the JSON or SQLite backend.

---

## Milestone 6 — Operability & polish (`v1.0`) ☑

Make a working census something you can run unattended: scheduled, locked,
notifying, publishable and reproducible in a container. The operability surface
lives in [operations.md](operations.md), with deploy recipes under
[`deploy/`](../deploy/).

- ☑ Scheduled scans (systemd timer / cron recipe) + lockfile. The CLI takes an
  advisory, PID-stamped lock at `<out>/.myinventory.lock` ([`lock.py`](../src/myinventory/lock.py))
  so an overrunning scheduled scan backs off instead of racing itself; stale
  locks (dead PID) are reclaimed. Units in [`deploy/`](../deploy/).
- ☑ Notifications on change (webhook / email) — opt-in. After a scan the diff
  against the previous snapshot is dispatched to Slack/JSON webhooks and SMTP
  email ([`notify/`](../src/myinventory/notify/)); stdlib-only, best-effort,
  off by default.
- ☑ HTML output: `render --html` assembles a self-contained static site
  ([`render/html.py`](../src/myinventory/render/html.py)), embedding the network
  diagram as SVG when the `d2` binary is present and degrading gracefully when
  it is not.
- ☑ Config profiles / multiple sites — `profiles:` overlays selected with
  `--profile`, plus a `site` label that flows into HTML titles and notification
  subjects.
- ☑ Hardening pass + container image ([`Dockerfile`](../Dockerfile), runs
  unprivileged, bundles all backends + `d2`). *(PyPI/`pipx` publishing
  deliberately deferred — install from source or the image for now.)*
- ☑ Comprehensive docs pass + tutorial walkthrough ([tutorial.md](tutorial.md),
  [operations.md](operations.md)).

**Exit criteria:** a systemd timer runs a locked nightly scan that publishes an
HTML site and pings a webhook when the LAN changes — all from one config that can
describe several sites.

---

## Beyond v1.0 (candidate backlog)

- Hyper-V and XCP-ng virtualization backends.
- Cloud inventory (AWS/Azure/GCP/Hetzner) as additional "virtualization"
  backends behind the same interface.
- Kubernetes cluster discovery (nodes + workloads).
- Mermaid / Graphviz renderers alongside D2.
- Web UI for browsing the inventory.
- Export to NetBox / device42 / other CMDBs.
- Passive discovery (sniff ARP/mDNS/LLDP) to complement active scans.

---

## Sequencing rationale

Milestones 1 and 2 are the two halves of the core promise ("services" and
"VMs"). They are deliberately ordered so that **host discovery (M1) exists
before virtualization correlation (M2)** — VM↔host linking needs the host side
to be real first. **M3 (SSH deep inspection)** then turns each Linux host from a
set of open ports into a real software/process/container inventory, reusing the
same host↔child linking pattern that M2 established for VMs. Everything from M4
on is accuracy, change-tracking and operability layered on a working core.
