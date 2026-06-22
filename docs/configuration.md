# Configuration

`myinventory` is driven by a single YAML file (default `./myinventory.yaml`,
overridable with `--config`). A working example lives at
[`examples/inventory.example.yaml`](../examples/inventory.example.yaml).

Validate a file without scanning:

```bash
myinventory validate-config --config myinventory.yaml
```

## Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `output_dir` | str | `./out` | Where `inventory.json`, diagrams and docs go. |
| `workers` | int | `64` | Thread-pool size for the service-probe stage. |
| `service_probes` | list | `[banner]` | Probes to run, in order. |
| `networks` | list | `[]` | Subnets to scan (see below). |
| `hypervisors` | list | `[]` | Hypervisors to enumerate VMs from. |
| `linux_ssh` | list | `[]` | Linux hosts to deep-inspect over SSH. |
| `enrichment` | map | *(on)* | Post-scan enrichment passes (see below). |
| `storage` | map | *(json)* | Persistence backend + change tracking (see below). |
| `notifications` | map | *(off)* | Webhook/email alerts on change (see below). |
| `site` | str | — | Label for this estate, used in titles + notifications. |
| `profiles` | map | `{}` | Named overlays for multiple sites in one file (see below). |

## `networks[]`

```yaml
networks:
  - name: lan
    cidr: 192.168.1.0/24
    vlan: 1
    discovery: [tcp]        # tcp | icmp | arp
    probe_ports: [22, 80, 443, 8006]   # optional liveness ports
    timeout: 0.5            # per-connection seconds
    workers: 128            # parallelism for this subnet
```

| Key | Required | Notes |
|---|---|---|
| `cidr` | ✓ | Any CIDR; `/24` etc. Host addresses are enumerated. |
| `name` | | Friendly label used in maps/docs. |
| `vlan` | | Informational. |
| `discovery` | | Backends to run. `icmp`/`arp` need the `[scan]` extra and usually root. |
| `probe_ports` | | Restrict the TCP liveness probe to these ports. |
| `timeout` / `workers` | | Tuning knobs for the sweep. |

## `hypervisors[]`

```yaml
hypervisors:
  - name: pve-1
    type: proxmox          # registry key: proxmox | vmware | libvirt
    host: 192.168.1.10
    username: root@pam
    token_name: myinventory
    secret: env:PROXMOX_TOKEN
    verify_tls: false
```

| Key | Required | Notes |
|---|---|---|
| `type` | ✓ | Selects the virtualization backend. |
| `host` | ✓ | Management endpoint (IP/hostname or URI for libvirt). |
| `username` | | API user. For Proxmox include the realm, e.g. `root@pam`. |
| `password` / `secret` / `token_name` | | Auth material; see secrets below. |
| `verify_tls` | | Set `false` for self-signed homelab certs. |

**Proxmox authentication** — choose one:

- **API token** (preferred — scoped, revocable): set `token_name` **and**
  `secret`.
- **Password login**: set `password` and leave the token fields unset.

```yaml
# token auth
- type: proxmox
  host: 192.168.1.10
  username: root@pam
  token_name: myinventory
  secret: env:PROXMOX_TOKEN

# password auth
- type: proxmox
  host: 192.168.1.11
  username: root@pam
  password: env:PVE_PASSWORD
```

A target with neither a complete token nor a password is a clear run-time error
naming the host.

**VMware (vCenter or standalone ESXi)** — `username` + `password`, against the
vCenter Server or an ESXi host directly. A read-only vSphere role is enough. Both
hosts and VMs are enumerated; each VM is linked to the ESXi host running it.

```yaml
- type: vmware
  host: vcenter.lab.local        # or a standalone ESXi IP
  username: readonly@vsphere.local
  password: env:VSPHERE_PASSWORD
  verify_tls: false              # accept self-signed homelab certs
```

**libvirt (KVM/QEMU)** — `host` is a libvirt **connection URI**, not an IP. The
daemon is opened read-only. Guest IPs come from the qemu-guest-agent when it is
running in the VM.

```yaml
- type: libvirt
  host: qemu+ssh://root@192.168.1.30/system   # remote over SSH
# host: qemu:///system                        # local daemon
```

Guest IP/MAC discovery is best-effort across all backends: a VM whose guest agent
(QEMU agent / VMware Tools) is absent still appears, just without addresses.

## `linux_ssh[]`

Linux hosts to inspect read-only over SSH (deep inspection — OS, packages,
processes, systemd units, Docker/Podman containers). Needs the `ssh` extra
(`pip install 'myinventory[ssh]'`).

Every command is screened against a read-only allow-list before it runs; `sudo`
is opt-in and used only for the commands that need it (listening-socket→process
mapping and the container runtime). Host-key checking is strict by default (the
host must be in `/etc/ssh/ssh_known_hosts` or your `~/.ssh/known_hosts`), and
`~/.ssh/config` is honored — including a `ProxyJump`/`ProxyCommand` entry for
bastion hosts. Set `strict_host_key: false` to auto-accept unknown host keys
(convenient on a homelab, weaker against MITM).

```yaml
linux_ssh:
  - name: app-1
    host: 192.168.1.20
    username: ops
    password: env:APP1_SSH_PASSWORD      # or key_file
    key_file: ~/.ssh/id_ed25519          # key and/or password
    sudo: true                           # elevate via sudo -S when needed
    sudo_password: env:APP1_SUDO_PASSWORD
    port: 22
```

| Key | Required | Default | Notes |
|---|---|---|---|
| `host` | ✓ | — | IP or hostname. |
| `username` | | `root` | SSH login user. |
| `password` | | — | Login password (secret reference). Use this **or** `key_file` (or both). |
| `key_file` | | — | Path to a private key for key-based auth. |
| `sudo` | | `false`¹ | Run privileged commands through `sudo -S`. |
| `sudo_password` | | — | Password piped to `sudo -S` (secret reference). Omit for passwordless sudo. |
| `port` | | `22` | SSH port. |
| `strict_host_key` | | `true` | Reject hosts not in a known_hosts file. `false` auto-accepts. |

¹ `sudo` defaults to `true` automatically when a `sudo_password` is supplied.

**Auth combinations**

| Goal | Set |
|---|---|
| Key login, no elevation | `key_file` |
| Key login, passwordless sudo | `key_file`, `sudo: true` |
| Key login, sudo needs a password | `key_file`, `sudo_password: env:…` |
| Password login + sudo password | `password: env:…`, `sudo_password: env:…` |

Most commands run unprivileged; `sudo`/`sudo_password` is only used for the few
that need it (e.g. mapping every listening socket to its owning process). Prefer
a key with passwordless, command-restricted sudo where you can — see
[security.md](security.md).

## `enrichment`

After discovery, virtualization and correlation, a set of **enrichment** passes
annotate the merged inventory in place — naming IP-only hosts, guessing each
host's OS and assigning a role and descriptive tags. The cheap, dependency-free
passes default **on**; SNMP is opt-in. See [enrichment.md](enrichment.md) for
what each pass does.

```yaml
enrichment:
  reverse_dns: true            # PTR lookups for IP-only hosts
  os_fingerprint: true         # OS guess from TTL + banners + open ports
  classify: true               # roles (nas/printer/network…) + tags
  dhcp_leases:                 # client hostnames from a lease database
    - /var/lib/misc/dnsmasq.leases
  snmp:
    enabled: true              # needs the [snmp] extra
    community: env:SNMP_COMMUNITY   # default "public"; env:/file: refs accepted
    version: "2c"              # "1" | "2c"
    port: 161
  rules:                       # user classification rules (run last)
    - hostname_regex: "^cam-"
      services: [rtsp]
      role: network
      tags: [camera, iot]
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `reverse_dns` | bool | `true` | Resolve PTR records for hosts with no name. |
| `dhcp_leases` | list | `[]` | dnsmasq / ISC `dhcpd.leases` files to read hostnames from. |
| `os_fingerprint` | bool | `true` | Heuristic OS guess (never overrides an SSH/SNMP OS). |
| `classify` | bool | `true` | Assign a role and tags from services, OS, vendor. |
| `snmp.enabled` | bool | `false` | Poll the SNMP `system` group (needs the `[snmp]` extra). |
| `snmp.community` | str | `public` | Community string; accepts `env:`/`file:` refs. |
| `snmp.version` | str | `2c` | `1` or `2c`. |
| `snmp.port` / `timeout` / `retries` | | `161` / `1.0` / `1` | UDP tuning. |
| `rules` | list | `[]` | Declarative classification rules (below). |

**Classification rules** — each rule fires only when *every* condition it sets
matches; the outcome assigns a `role` and/or appends `tags`. User rules run
after the built-in heuristics and, being explicit, may override the role.

| Field | Matches when |
|---|---|
| `ports` | any listed port is open on the host. |
| `services` | any listed logical service name is present. |
| `os_contains` | substring of the host's OS string (case-insensitive). |
| `vendor_contains` | substring of the MAC-derived vendor. |
| `hostname_regex` | regex search against the hostname. |
| `role` / `tags` | outcome applied on a match. |

## `storage`

Where the inventory is persisted and how change tracking behaves (Milestone 5).

```yaml
storage:
  backend: json            # json | sqlite
  keep_history: true       # snapshot every scan for diffs/changelog/stale
  stale_after_scans: 3     # absence threshold reported by `list --stale`
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `backend` | str | `json` | `json` → `inventory.json` + `history/`; `sqlite` → `inventory.db`. |
| `keep_history` | bool | `true` | Record a per-scan snapshot. With it off, `diff`/`changelog`/`--stale` have nothing to compare. |
| `stale_after_scans` | int | `3` | Default N for stale-host detection. |

Each scan is snapshotted **before** it merges into the cumulative state, so the
history reflects exactly what each scan saw — the only way removals and drift are
detectable, since the merge never drops a host.

## `notifications`

Opt-in alerts sent after a scan, when the diff against the previous snapshot is
non-empty (Milestone 6). Both channels use only the standard library, so they
add no install dependency. A failing channel is recorded as a scan error, never
fatal. See [operations.md](operations.md).

```yaml
notifications:
  enabled: true
  on_change_only: true         # set false to notify after every scan
  webhooks:
    - url: https://hooks.slack.com/services/XXX/YYY/ZZZ
      format: slack            # slack | json
    - url: https://example.com/inventory-hook
      format: json
      headers:
        Authorization: env:HOOK_TOKEN     # static headers (refs allowed)
  email:
    host: smtp.example.com
    port: 587
    sender: inventory@example.com
    recipients: [ops@example.com]   # a bare string is accepted too
    username: inventory@example.com
    password: env:SMTP_PASSWORD
    use_tls: true              # STARTTLS
    subject_prefix: "[inv] "
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch for all channels. |
| `on_change_only` | bool | `true` | Skip notifying when nothing changed. |
| `webhooks[].url` | str | — | Endpoint to POST to (required per entry). |
| `webhooks[].format` | str | `json` | `json` (`{title,summary,body,diff}`) or `slack` (`{text}`). |
| `webhooks[].headers` | map | `{}` | Extra request headers. |
| `email.host` / `sender` | str | — | Required when an `email` block is present. |
| `email.recipients` | list | `[]` | One or more addresses. |
| `email.use_tls` | bool | `false` | Use STARTTLS. |
| `email.username` / `password` | | — | Auth (attempted only when `username` is set). |

The first scan against an empty history never notifies — there is nothing to
compare against yet.

## `profiles` and `site`

A single config file can describe several estates. `profiles` is a map of
named overlays; selecting one with `--profile NAME` deep-merges its keys over the
base document. Nested maps merge key-by-key; lists (and scalars) are replaced
wholesale. The selected profile name also becomes the default `site` label
(used in HTML titles and notification subjects).

```yaml
# shared base
workers: 64
storage: { backend: json }
enrichment: { classify: true }

profiles:
  home:
    site: home-lab
    networks:
      - { cidr: 192.168.1.0/24, discovery: [tcp, arp] }
  office:
    site: hq
    storage: { backend: sqlite }      # overrides just the backend
    networks:
      - { cidr: 10.0.0.0/24, discovery: [tcp] }
```

```bash
myinventory report -c sites.yaml --profile home   -o ./out/home
myinventory report -c sites.yaml --profile office -o ./out/office
```

`validate-config` lists the available profiles; pass `--profile` to validate a
specific overlay. With no `--profile`, only the base document is used.

## Secrets

Credentials are **never** written inline. Every secret field — `password`,
`secret`, `sudo_password`, the SNMP `community` and the notification email
`password` — takes a *reference* that is resolved at run time:

| Form | Resolves to |
|---|---|
| `env:NAME` | The value of environment variable `NAME`. |
| `file:/path/to/secret` | The file's contents, trimmed. |
| any other string | Used verbatim (discouraged). |

A referenced env var that is unset, or a missing secret file, is a hard config
error — you find out before the scan starts, not midway through. See
[security.md](security.md) for the rationale.
