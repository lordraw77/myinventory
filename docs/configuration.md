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

## `linux_ssh[]`

Linux hosts to inspect read-only over SSH (deep inspection — OS, packages,
processes, systemd units, Docker/Podman containers; roadmap M3).

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

## Secrets

Credentials are **never** written inline. Every secret field — `password`,
`secret` and `sudo_password` — takes a *reference* that is resolved at run time:

| Form | Resolves to |
|---|---|
| `env:NAME` | The value of environment variable `NAME`. |
| `file:/path/to/secret` | The file's contents, trimmed. |
| any other string | Used verbatim (discouraged). |

A referenced env var that is unset, or a missing secret file, is a hard config
error — you find out before the scan starts, not midway through. See
[security.md](security.md) for the rationale.
