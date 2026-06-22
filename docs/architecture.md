# Architecture

This document describes how `myinventory` is structured, how data flows through
it, and the extension points that let you add new discovery and virtualization
backends.

## 1. Design goals

1. **Agentless.** Never require software on the targets. Use network probes and
   read-only API/SSH access only.
2. **Pluggable.** Discovery, service fingerprinting, virtualization backends and
   renderers are all plugins behind small interfaces. Adding "support for
   Hyper-V" or "render to Mermaid" must not touch the core.
3. **Normalized.** Every backend, however different, produces the same
   `Host` / `Service` / `VirtualMachine` objects. Renderers never know how a
   fact was discovered.
4. **Idempotent & diffable.** Re-running a scan produces stable host IDs so the
   JSON/Markdown output diffs cleanly in git. A scan *merges* into the prior
   inventory rather than replacing it.
5. **Fail soft.** A timeout against one host, or a hypervisor being down, must
   never abort the whole census. Errors are collected, not fatal.

## 2. High-level data flow

```
            ┌────────────┐
 config ───▶│ Orchestrator│
            └─────┬──────┘
                  │ schedules stages
   ┌──────────────┼───────────────────────────┐
   ▼              ▼                             ▼
┌─────────┐  ┌──────────────┐          ┌───────────────────┐
│Host     │  │Service       │          │Virtualization     │
│Discovery│  │Discovery     │          │Backends           │
│(sweep)  │  │(fingerprint) │          │(Proxmox/VMware/…) │
└────┬────┘  └──────┬───────┘          └─────────┬─────────┘
     │ hosts        │ services                   │ vms + hypervisor link
     └──────────────┴───────────┬────────────────┘
                                ▼
                         ┌─────────────┐
                         │  Inventory  │  (normalized model, in memory)
                         └──────┬──────┘
                                │ merge + persist
                                ▼
                         ┌─────────────┐
                         │  Storage    │  inventory.json (+ history)
                         └──────┬──────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                                ▼
         ┌────────────┐                   ┌────────────┐
         │ D2 Renderer│                   │ MD Renderer│
         └─────┬──────┘                   └─────┬──────┘
               ▼                                ▼
         diagrams/*.d2                     docs/*.md
```

The pipeline has two top-level commands:

- `scan` — runs discovery + virtualization stages, merges into the inventory,
  and persists `inventory.json`.
- `render` — reads a persisted `inventory.json` and runs the renderers. Kept
  separate so you can re-render without re-scanning, and so rendering is a pure,
  testable function of the model.

## 3. Components

### 3.1 Configuration (`myinventory.config`)
Loads and validates the YAML config into typed objects (`AppConfig`,
`NetworkTarget`, `HypervisorTarget`, `CredentialRef`). Credentials are
*referenced* here, never stored inline — see [security.md](security.md).

### 3.2 Data model (`myinventory.models`)
Plain dataclasses with no I/O: `Host`, `Service`, `VirtualMachine`, `Network`,
`Inventory`. This is the contract every other component speaks. See
[data-model.md](data-model.md).

### 3.3 Host discovery (`myinventory.discovery`)
Finds *which IPs are alive*. A `HostDiscovery` plugin takes a `NetworkTarget`
and yields bare `Host` objects (address + how it was found). Built-in
strategies:

- `icmp` — ping sweep.
- `arp` — ARP scan on the local L2 segment (most reliable on a LAN).
- `tcp` — TCP-connect to a small set of common ports (works through firewalls
  that drop ICMP).

Backends can be combined; results are merged by address.

### 3.4 Service discovery (`myinventory.services`)
Given a discovered `Host`, finds *what it runs*. A `ServiceProbe` inspects one
or more ports and returns `Service` objects with a best-effort
product/version. Two tiers:

- **Port scan + banner grab** (no credentials): connect, read the banner, match
  it against a signature table.
- **Authenticated probes** (optional, with SSH/SNMP creds): richer detail such
  as the exact package version or systemd unit list.

An optional `nmap` backend wraps the `nmap` binary when present for stronger
fingerprinting.

### 3.5 Virtualization backends (`myinventory.virtualization`)
The headline feature. A `VirtualizationBackend` connects to a hypervisor's
management API and returns the `VirtualMachine`s it hosts, linked back to the
hypervisor `Host`. Backends share one interface; concrete ones:

- `proxmox` — Proxmox VE (via `proxmoxer`).
- `vmware` — vCenter / standalone ESXi (via `pyvmomi`).
- `libvirt` — KVM/QEMU/LXC (via `libvirt-python`).
- *(roadmap)* `hyperv`, `xcpng`, cloud providers.

Each backend is selected from a **registry** keyed by `type` in the config, so
adding one is "write a class, register it."

### 3.6 Pipeline / Orchestrator (`myinventory.pipeline`)
Owns execution: resolves which plugins to run from config, fans work out across
a bounded thread pool (discovery is I/O-bound), enforces per-target timeouts and
rate limits, collects errors, and merges every plugin's output into a single
`Inventory`. Correlation lives here too — e.g. matching a VM's reported IP to a
separately discovered `Host` so the two records link up.

### 3.7 Storage (`myinventory.storage`)
Serializes the `Inventory` to `inventory.json` and merges a new scan into a
prior one using stable IDs (last-seen wins, history preserved). JSON is the
default; the repository interface allows SQLite later without touching callers.

### 3.8 Renderers (`myinventory.render`)
Pure functions `Inventory -> files`:

- **D2 renderer** — emits `.d2` for: a full network map, one diagram per subnet,
  and a hypervisor/VM relationship map.
- **Markdown renderer** — emits an `index.md`, per-host pages, and
  service/VM summary tables.

Renderers are deliberately dumb: all correlation/enrichment happened upstream.

### 3.9 CLI (`myinventory.cli`)
Thin argument parsing over the pipeline and renderers. Commands: `scan`,
`render`, `report` (scan+render), `list`, `validate-config`.

## 4. The plugin model

Three registries, one pattern. A plugin is a class implementing the relevant
ABC and registered under a string key:

```python
@register_backend("proxmox")
class ProxmoxBackend(VirtualizationBackend):
    def collect(self, target: HypervisorTarget) -> BackendResult:
        ...
```

The orchestrator looks the key up from config (`type: proxmox`) and never
imports the concrete class directly. This keeps optional heavy dependencies
(`pyvmomi`, `libvirt`) import-isolated: a backend only imports its SDK inside
its module, so a base install without `[virt]` still runs.

See [contributing.md](contributing.md) for a step-by-step plugin walkthrough.

## 5. Concurrency & resilience

- Discovery and virtualization stages run on a bounded `ThreadPoolExecutor`
  (network I/O, not CPU). Worker count and per-target timeout are configurable.
- Every plugin call is wrapped so an exception becomes a recorded
  `ScanError` attached to the result, never an aborted run.
- Rate limiting (max probes/sec) protects fragile devices and keeps the scan
  under IDS thresholds.
- The run is **idempotent**: stable IDs mean a second run updates timestamps and
  changed fields without duplicating records.

## 6. Identity & correlation

Stable identity is what makes the output diffable. Host ID is derived in
priority order: **MAC address → primary IP → hostname**. VMs use the
hypervisor-assigned UUID. After all stages run, the orchestrator correlates:

- VM reported IPs ↔ separately discovered hosts (so a VM and its network-visible
  host become one linked record).
- Hypervisor management IP ↔ a discovered host (so the hypervisor node in the
  map is the same node found by the sweep).

## 7. Technology choices (summary)

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python ≥3.9 | Ubiquitous on servers, rich net/virt libraries. |
| Model | `dataclasses` | Zero-dep, typed, trivially serializable. |
| Config | YAML | Human-friendly; comments for documenting a homelab. |
| Concurrency | threads | Workload is I/O-bound; avoids async backend complexity. |
| Diagrams | D2 | Text-based, diffable, great auto-layout, container support. |
| Docs | Markdown | Universal; renders in any wiki/SSG. |
| Persistence | JSON (→ SQLite) | Diffable now, queryable later behind one interface. |

The longer "why" for each lives in [docs/adr/](adr/).

## 8. Directory layout

```
src/myinventory/
├── cli.py                 # command-line entrypoint
├── config.py              # YAML -> typed config
├── models/                # Host, Service, VirtualMachine, Inventory
├── discovery/             # host discovery plugins (icmp/arp/tcp)
├── services/              # service fingerprinting + probes/
├── virtualization/        # hypervisor backends + registry
├── pipeline/              # orchestrator, correlation, errors
├── storage/               # inventory.json repository + merge
└── render/                # d2.py, markdown.py
```
