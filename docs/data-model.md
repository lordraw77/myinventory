# Data model

Everything in `myinventory` flows through one small set of dataclasses defined
in [`src/myinventory/models/`](../src/myinventory/models). They carry no I/O and
no backend-specific logic, so discovery, storage and rendering all agree on the
same shapes.

```
Inventory
├── networks: List[Network]
├── hosts:    Dict[str, Host]        # keyed by stable id
│     └── services: List[Service]
└── vms:      Dict[str, VirtualMachine]
```

## Host

A node in the inventory — physical machine, appliance, hypervisor, or a VM that
is reachable on the network.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Stable identity. See **Identity** below. |
| `addresses` | `List[str]` | IPv4/IPv6 addresses; `addresses[0]` is primary. |
| `hostname` | `str?` | DNS / reported name. |
| `mac` | `str?` | Normalized lower-case, colon-separated. |
| `role` | `HostRole` | `unknown`/`physical`/`hypervisor`/`vm`/`container`/`network`/`nas`/… |
| `os` | `str?` | Best-effort OS string. |
| `services` | `List[Service]` | Keyed internally by `proto/port`. |
| `tags` | `List[str]` | Free-form classification. |
| `sources` | `List[DiscoverySource]` | How it was found (`tcp`, `arp`, `virtualization`…). |
| `packages` | `List[Package]` | Installed software (SSH deep inspection). |
| `processes` | `List[Process]` | Notable running processes (SSH deep inspection). |
| `containers` | `List[Container]` | Containers reported by the host's runtime. |
| `hypervisor_id` | `str?` | Set when this host is a VM, links to its hypervisor. |
| `hosted_vm_ids` | `List[str]` | Set on a hypervisor. |
| `first_seen` / `last_seen` | `str?` | ISO-8601 UTC timestamps. |

OS facts gathered over SSH (kernel release, arch, uptime, virtualization hint,
`systemd_units`, package count) are stored under `extra`.

### Identity

`Host.compute_id()` derives the ID in priority order:

1. **MAC** → `mac:aa:bb:cc:dd:ee:ff` (most stable — survives DHCP changes)
2. **IP** → `ip:192.168.1.10`
3. **hostname** → `host:web-1`

Stable IDs are what make re-scans produce a clean diff instead of duplicate
records, and what let correlation link a VM to its network-visible host.

## Service

A single network service on a host.

| Field | Type | Notes |
|---|---|---|
| `port` / `protocol` | `int` / `str` | `tcp` or `udp`. |
| `name` | `str?` | Logical service: `http`, `ssh`, `postgresql`. |
| `product` / `version` | `str?` | Concrete software when fingerprinted. |
| `state` | `str` | `open`/`filtered`/`closed`. |
| `banner` | `str?` | Raw connect banner, when captured. |
| `source` | `str?` | Detecting probe: `banner`, `nmap`, `ssh-probe`. |

Identity within a host is `proto/port`, so re-probing replaces rather than
duplicates.

## VirtualMachine

A guest enumerated from a virtualization backend.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Hypervisor-assigned UUID / stable key. |
| `name` | `str` | Display name. |
| `hypervisor_id` | `str` | The host running it. |
| `backend` | `str` | `proxmox`/`vmware`/`libvirt`. |
| `power_state` | `PowerState` | `running`/`stopped`/`paused`/`unknown`. |
| `vcpus`/`memory_mb`/`disk_gb` | nums | Allocated resources. |
| `guest_os` | `str?` | As reported by the hypervisor / guest agent. |
| `addresses`/`mac_addresses` | `List[str]` | Used for correlation to a `Host`. |
| `host_id` | `str?` | Set by correlation when the guest is also a discovered host. |

## Package, Process, Container

Deep-inspection records produced by the SSH inspectors (M3); they hang off a
`Host`.

**Package** — installed software normalized across managers: `name`,
`version?`, `manager` (`dpkg`/`rpm`/`snap`/`flatpak`).

**Process** — a notable running process: `pid`, `name`, `user?`,
`cpu_percent?`, `rss_kb?`, `command?`, and `listening_ports` (filled by
socket↔process correlation, so the host page shows which process owns each open
port).

**Container** — a container reported by the host's runtime: `id`, `name`,
`image?`, `state?`, `runtime` (`docker`/`podman`), `ports`, `mounts`,
`restart_policy?`, `compose_project?`, `labels`. `published_ports` maps the
host-side ports back to the host's network-discovered services, so
`host:8080 → nginx` links to `container web-1 → nginx:1.25`. Containers render
nested under their host in `containers.d2`, mirroring the hypervisor→VM view.

## Network

A scanned subnet — `cidr`, optional `name`/`vlan`/`description`. Used to group
hosts into D2 containers and Markdown sections; `contains(address)` does the
membership test.

## Inventory

The aggregate root. Key behaviors:

- **`upsert_host` / `upsert_vm`** — insert or field-level merge by ID.
- **`merge(other)`** — fold a prior scan in (used by storage for idempotency).
- **`to_json` / `from_json`** — stable serialization (`schema_version` = 1).
- **Queries** — `hosts_in(network)`, `vms_of(hypervisor_id)`, `network_for(ip)`.

The merge rule is "non-empty incoming value wins, lists are unioned, timestamps
advance" — see `_merge_host` in
[inventory.py](../src/myinventory/models/inventory.py).
