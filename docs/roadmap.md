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

## Milestone 2 — Virtualization (`v0.3`) — *headline feature*

Enumerate VMs and link them to their hypervisor.

- ☐ `VirtualizationBackend` lifecycle finalized (connect → collect → close).
- ☐ Proxmox VE backend (`proxmoxer`): nodes, VMs/LXC, status, resources, IPs.
- ☐ libvirt backend (KVM/QEMU): domains, state, resources, guest IPs via agent.
- ☐ VMware backend (`pyvmomi`): vCenter + standalone ESXi, VMs, resource pools.
- ☐ Correlation: VM IPs ↔ discovered hosts; hypervisor mgmt IP ↔ host node.
- ☐ D2 hypervisor map showing host containers with nested VM nodes.

**Exit criteria:** a Proxmox/ESXi node in config produces a map where the host
box contains its running VMs, cross-linked to network discovery.

---

## Milestone 3 — Agentless Linux deep inspection over SSH (`v0.4`)

Go beyond "a port is open": log into Linux servers read-only over SSH and
inventory what actually runs on them — installed software, running processes and
Docker workloads. Still agentless: a short-lived SSH session running read-only
commands, no software left behind.

- ☑ Config surface: a `linux_ssh` target block — `username`, `password`,
  `key_file`, `sudo`, `sudo_password`, `port` — with every secret resolved via
  the `env:`/`file:` reference scheme. *(landed early)*
- ☐ SSH transport layer (paramiko): connect using SSH key/agent and/or
  username+password auth, run privileged commands via `sudo -S` fed the
  configured `sudo_password` (or passwordless sudo), honor `~/.ssh/config`,
  bastion/jump-host support, strict host-key checking, per-host timeout.
- ☐ Base OS facts: distro + version (`/etc/os-release`), kernel (`uname`),
  architecture, uptime, virtualization hint (`systemd-detect-virt`).
- ☐ **Installed software**: package inventory across managers — `dpkg`/`apt`
  (Debian/Ubuntu), `rpm`/`dnf` (RHEL/Fedora/Rocky), plus `snap`/`flatpak`
  when present. Normalized to `(name, version, manager)`.
- ☐ **Running processes & listening sockets**: `ss -tulpn` → map each listening
  port to its owning process/unit, enriching the `Service` records from network
  discovery with the real binary and PID. Top processes by CPU/RSS.
- ☐ **systemd services**: enabled/running units (`systemctl list-units`) so the
  inventory reflects intended services, not just currently-open ports.
- ☐ **Docker / container runtime discovery**:
  - Detect the runtime (docker / podman / containerd) and its version.
  - Enumerate containers (`docker ps -a` / `podman ps -a` / Docker socket API):
    name, image + tag/digest, state, ports published to the host, mounts,
    restart policy, compose project/labels.
  - Enumerate local images, networks and named volumes.
  - Map published container ports back to the host's network-discovered
    services (so "host:8080 → nginx" links to "container web-1 → nginx:1.25").
- ☐ Data model: add `Package`, `Process`, and `Container` records (a container
  reuses the `HostRole.CONTAINER` node so it appears in maps/docs, linked to its
  host the way a VM links to its hypervisor).
- ☐ Rendering: container nodes nested under their Docker host in D2 (mirroring
  the hypervisor→VM view); per-host Markdown gains **Packages**, **Processes**
  and **Containers** sections.
- ☐ Safety: read-only command allow-list, `sudo` strictly opt-in (off unless
  configured) and used only for the commands that require it, configurable
  command set, graceful degradation when a command is missing.
- ☐ Integration test against a docker-compose lab (a Linux box running a couple
  of containers) asserting containers + packages are discovered.

**Exit criteria:** pointing `myinventory` at a Linux host with Docker yields its
OS, installed packages, running services and a list of containers — rendered in
both the D2 map and the host's Markdown page.

---

## Milestone 4 — Enrichment & accuracy (`v0.5`)

- ☐ SNMP probe for network appliances (switches, APs, NAS).
- ☐ OS fingerprint heuristics (TTL, banner, open-port profile).
- ☐ Reverse-DNS and DHCP-lease hostname resolution.
- ☐ Tagging/classification rules (role: hypervisor / nas / router / printer…).

---

## Milestone 5 — Change tracking & reporting (`v0.6`)

- ☐ History: keep prior scans; compute a diff between two inventories.
- ☐ `myinventory diff` command (new/removed hosts, changed services, drifted
  VMs).
- ☐ Markdown changelog page per scan.
- ☐ Optional SQLite backend behind the existing repository interface.
- ☐ "Stale host" detection (not seen in N scans).

---

## Milestone 6 — Operability & polish (`v1.0`)

- ☐ Scheduled scans (systemd timer / cron recipe) + lockfile.
- ☐ Notifications on change (webhook / email) — opt-in.
- ☐ HTML output (render D2 → SVG and assemble a static site).
- ☐ Config profiles / multiple sites.
- ☐ Hardening pass, packaging to PyPI, `pipx` install, container image.
- ☐ Comprehensive docs pass + tutorial walkthrough.

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
