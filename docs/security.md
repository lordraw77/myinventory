# Security & safety

`myinventory` performs **active** network discovery and connects to hypervisor
management APIs. Used carelessly it can trip alarms or expose credentials. This
page covers using it responsibly.

## Authorization

Only scan networks you own or are explicitly authorized to assess. Active
discovery (ICMP/ARP/TCP probes) generates traffic that intrusion-detection
systems will flag and that some devices handle poorly. On corporate networks,
get written authorization first.

## Be a good citizen on the wire

- The `tcp` backend opens real connections. Keep `probe_ports` small and
  `timeout` modest on fragile networks.
- Rate limiting (roadmap M1) caps probes/sec to stay under IDS thresholds and
  avoid overwhelming low-power devices (IoT, printers, embedded gear).
- Prefer `arp` on a LAN: it is lighter and stays on the local segment.

## Credential handling

The tool is **agentless and read-only by design** — it never needs write access
to a hypervisor or a shell on a target.

- **Never inline secrets in the config.** Use `env:NAME` or `file:/path`
  references (see [configuration.md](configuration.md)). A referenced secret
  that is missing is a hard error, surfaced before the scan starts.
- **Use least privilege.** Create a dedicated read-only API user/token per
  hypervisor:
  - Proxmox: a token with `PVEAuditor` on `/`.
  - VMware: a read-only role at the vCenter/ESXi root.
  - libvirt: connect over `qemu+ssh` with an unprivileged, restricted account.
- **Use API tokens over passwords** where the platform supports them; tokens are
  scoped and revocable.
- **TLS:** `verify_tls: false` exists for self-signed homelab certs. Prefer a
  proper cert and leave verification on for anything that matters.

### Linux SSH inspection

The `linux_ssh` deep-inspection probe logs into Linux hosts read-only. Harden
it as follows:

- **Prefer keys over passwords.** Use `key_file` with a dedicated, restricted
  account rather than a login `password` where you can.
- **Keep `sudo` opt-in and minimal.** It is off unless you set it. Most commands
  run unprivileged; only a few (e.g. mapping every socket to its process) need
  elevation. Prefer a **passwordless, command-restricted sudoers** entry (an
  allow-list of the exact read-only commands) over storing a `sudo_password`.
- **If you must store a `sudo_password`**, put it behind an `env:`/`file:`
  reference like any other secret — never inline. It is passed to `sudo -S` over
  the encrypted SSH channel and is never written to the inventory output.
- **Least privilege account.** The inspection user needs read access only; it
  never modifies the target.

## What ends up in the output

`inventory.json`, the D2 maps and the Markdown docs describe your network —
addresses, hostnames, service versions, VM names. Treat them as **sensitive**:

- Don't commit them to a public repository.
- Service banners/versions are exactly what an attacker would want for
  vulnerability matching. Store the output somewhere access-controlled.

## Threat-model note

This is an inventory tool, not a vulnerability scanner. It records *what is
running*, not *what is exploitable*. Banner-based version detection is
best-effort and can be wrong (spoofed banners, reverse proxies) — verify before
acting on it.
