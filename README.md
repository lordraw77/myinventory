# myinventory

**Agentless network census** for homelabs and small/medium server estates.

`myinventory` scans the networks you point it at, discovers reachable hosts and
the services they run, talks to your hypervisors to enumerate virtual machines,
and turns the result into:

- **[D2](https://d2lang.com/) diagrams** — visual maps of subnets, hosts,
  hypervisors and the VMs they host.
- **Markdown documentation** — a browsable inventory with per-host pages and
  summary tables, suitable for a wiki or a static-site generator.

The whole pipeline is **agentless**: nothing is installed on the target
machines. Discovery uses standard network probes (ICMP/ARP/TCP) and read-only
API/SSH access where credentials are provided.

> Status: early development (`v0.1.0`). The architecture, data model and
> renderers are defined; discovery and virtualization backends are being
> implemented per the [roadmap](docs/roadmap.md).

---

## Why

Most homelabs and small estates have no source of truth. Machines come and go,
VMs get spun up on a hypervisor and forgotten, and the only "documentation" is
in someone's head. `myinventory` rebuilds that picture automatically and keeps
it in a diffable, version-controllable form (D2 + Markdown).

## Key features

| Capability | What it does |
|---|---|
| Host discovery | Sweep one or more CIDR ranges (ICMP / ARP / TCP-SYN) to find live hosts. |
| Service discovery | Fingerprint open ports into named services (ssh, http, postgres, …). |
| VM discovery | Connect to Proxmox / VMware / libvirt and enumerate guests + their host. |
| Normalized model | One inventory model regardless of how a fact was discovered. |
| D2 maps | Network topology, hypervisor→VM relationships, per-subnet views. |
| Markdown + HTML | Index + per-host pages + service/VM tables; `--html` builds a static site. |
| Repeatable | Stable host IDs so re-scans produce diffs, not noise. |
| Operable | Scheduled + locked scans, opt-in webhook/email alerts on change, multi-site profiles, container image. |

## Quick start

```bash
# 1. install (base + the backends you need)
pip install -e ".[scan,virt,ssh]"

# 2. create a config describing what to scan
cp examples/inventory.example.yaml myinventory.yaml
$EDITOR myinventory.yaml

# 3. run a full census
myinventory scan --config myinventory.yaml --out ./out

# 4. render outputs
myinventory render --in ./out/inventory.json --out ./out

# results:
#   ./out/inventory.json     normalized inventory
#   ./out/diagrams/*.d2      D2 maps
#   ./out/docs/*.md          Markdown documentation
```

Render the D2 files to SVG/PNG with the [`d2`](https://d2lang.com/) CLI:

```bash
d2 out/diagrams/network.d2 out/network.svg
```

## Documentation

- [Architecture](docs/architecture.md) — components, data flow, plugin model.
- [Roadmap](docs/roadmap.md) — milestones from MVP to v1.0.
- [Data model](docs/data-model.md) — Host / Service / VirtualMachine / Inventory.
- [Discovery](docs/discovery.md) — how hosts, services and VMs are found.
- [Configuration](docs/configuration.md) — the YAML config reference.
- [Output formats](docs/output-formats.md) — D2, Markdown and HTML generation.
- [Usage](docs/usage.md) — CLI reference and workflows.
- [Tutorial](docs/tutorial.md) — zero-to-published-map walkthrough.
- [Operations](docs/operations.md) — scheduling, notifications, profiles, Docker.
- [Security & safety](docs/security.md) — scanning responsibly, credential handling.
- [Contributing](docs/contributing.md) — writing new discovery/virt plugins.
- [Architecture decisions](docs/adr/) — the "why" behind key choices.

## Legal / safety note

Only scan networks you own or are explicitly authorized to assess. Active
discovery generates traffic that intrusion-detection systems will flag. See
[docs/security.md](docs/security.md).

## License

MIT — see [LICENSE](LICENSE).
