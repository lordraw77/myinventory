# Discovery

How `myinventory` finds things. There are three discovery surfaces, each a
plugin layer with its own registry.

## 1. Host discovery — *which addresses are alive*

Plugins implement [`HostDiscovery`](../src/myinventory/discovery/base.py) and
return bare `Host` objects (address + source). Configure per-network via
`discovery: [...]`.

| Backend | Extra | Root? | How it works | Best for |
|---|---|---|---|---|
| `tcp` | none | no | TCP-connect to common ports; alive if any accepts. | Firewalled hosts, no privileges. |
| `icmp` *(M1)* | `[scan]` | usually | ICMP echo sweep. | Fast, permissive LANs. |
| `arp` *(M1)* | `[scan]` | yes | ARP requests on the local L2 segment. | Most reliable on a LAN; also yields MACs. |

The `tcp` backend ships today as the dependency-free reference implementation;
`icmp`/`arp` land in milestone 1. Results from multiple backends are merged by
address, so you can combine them (e.g. `arp` for MACs + `tcp` for reachability).

## 2. Service discovery — *what a host runs*

Plugins implement [`ServiceProbe`](../src/myinventory/services/base.py) and
return `Service` objects for a given host. Run in the order listed under
`service_probes`.

| Probe | Extra | Auth | Detail level |
|---|---|---|---|
| `banner` | none | none | Connect, grab banner, match a signature table; falls back to well-known-port names. |
| `nmap` *(M1)* | `[scan]` + `nmap` binary | none | Full nmap service/version detection when available. |
| `ssh` *(M3)* | `[ssh]` | SSH key/agent | Deep Linux inspection — see below. |
| `snmp` *(M4)* | | community/v3 | Appliance details (switches, APs, NAS). |

The banner probe and its [signature table](../src/myinventory/services/probes/signatures.py)
are intentionally small and easy to extend.

### Linux deep inspection over SSH (M3)

The `ssh` probe is the agentless way to look *inside* a Linux host instead of
just at its open ports. It opens a short-lived, read-only SSH session and runs a
fixed allow-list of commands, then closes — nothing is installed on the target.
It collects:

- **OS facts** — distro/version (`/etc/os-release`), kernel, arch, uptime.
- **Installed software** — packages across `dpkg`/`rpm`/`snap`/`flatpak`,
  normalized to `(name, version, manager)`.
- **Processes & listening sockets** — `ss -tulpn` maps each open port to its
  owning binary/unit, enriching the network-discovered `Service` records.
- **systemd units** — enabled/running services (intended state, not just
  currently-open ports).
- **Docker / Podman / containerd** — runtime + version, and per container its
  name, image+tag, state, published ports, mounts and compose labels; plus local
  images, networks and volumes. Published container ports are linked back to the
  host's network services.

Containers become `HostRole.CONTAINER` nodes linked to their host, so they show
up nested in the D2 map and in the host's Markdown page — the same host↔child
pattern used for hypervisor↔VM. Configured via a `linux_ssh` target block; see
[roadmap M3](roadmap.md#milestone-3--agentless-linux-deep-inspection-over-ssh-v04).

## 3. Virtualization — *which VMs exist and where*

The headline feature. Plugins implement
[`VirtualizationBackend`](../src/myinventory/virtualization/base.py) with a
`connect → collect → close` lifecycle and return both the hypervisor host(s) and
their VMs.

| Backend | Extra | API | Status |
|---|---|---|---|
| `proxmox` | `[virt]` | Proxmox VE REST (`proxmoxer`) | reference impl (M2) |
| `libvirt` | `[virt]` | libvirt (KVM/QEMU/LXC) | M2 |
| `vmware` | `[virt]` | vSphere/ESXi (`pyvmomi`) | M2 |
| `hyperv`, `xcpng`, cloud | — | — | backlog |

Each backend imports its SDK lazily, so a base install without `[virt]` still
imports and runs the network stages.

## Correlation

After all stages run, the orchestrator links the surfaces together:

- A VM's reported IP is matched to a separately discovered host → the VM gets a
  `host_id` and the host gets a `hypervisor_id`. The two records become one
  linked entity in maps and docs.
- A hypervisor's management IP is matched to a discovered host so the hypervisor
  node in the map is the same node the sweep found.

See [`_correlate`](../src/myinventory/pipeline/orchestrator.py).

## Adding a backend

All three layers share the same pattern: subclass the ABC, decorate with
`@register_*("name")`, keep heavy imports local. Full walkthrough in
[contributing.md](contributing.md).
