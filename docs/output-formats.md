# Output formats

`myinventory render` turns a persisted `inventory.json` into two artifact sets.
Both renderers are **pure functions of the model** — they do no scanning, so you
can re-render anytime without touching the network.

```
out/
├── inventory.json          # the normalized model (source of truth)
├── diagrams/
│   ├── network.d2          # all subnets, each a container of hosts
│   ├── hypervisors.d2      # each hypervisor containing its VMs
│   └── subnet-<name>.d2    # one focused diagram per subnet
└── docs/
    ├── index.md            # summary + subnet tables + VM overview
    └── hosts/<id>.md       # one page per host
```

## D2 diagrams

[D2](https://d2lang.com/) is a text-based diagram language with automatic
layout and container support — ideal because the output is **diffable** and
regenerates deterministically.

Hosts are styled by role (hypervisors blue, VMs green, network gear yellow
hexagons, NAS purple cylinders) and labeled with their top services.
Hypervisors are containers with their VMs nested inside, power state shown as
▶/⏹.

Render to an image with the `d2` CLI (installed separately):

```bash
d2 out/diagrams/network.d2      out/network.svg
d2 out/diagrams/hypervisors.d2  out/hypervisors.png
# live preview while editing:
d2 --watch out/diagrams/network.d2
```

Example (`hypervisors.d2`):

```d2
ip_192_168_1_10: "🖥  pve-1" {
  style.fill: "#dbeafe"
  proxmox_pve_1_101: "▶ web-1" {shape: rectangle}
  proxmox_pve_1_102: "⏹ db-1" {shape: rectangle}
}
```

## Markdown documentation

Plain Markdown that renders in any wiki, on GitHub/GitLab, or through a
static-site generator (MkDocs, Hugo, Docusaurus).

- **`index.md`** — counts, a table per subnet (host → address → role →
  services), and a per-hypervisor VM table.
- **`hosts/<id>.md`** — a fact table, the service list, any hosted VMs, and a
  link to the hypervisor when the host is a guest.

Links between pages are relative, so the `docs/` tree is self-contained and
portable.

## Why two formats

The D2 maps answer *"what does my network look like?"* at a glance; the Markdown
answers *"tell me everything about host X"* and is greppable/diffable in git.
Both derive from the same `inventory.json`, so they never disagree.
