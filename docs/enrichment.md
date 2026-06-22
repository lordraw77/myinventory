# Enrichment & accuracy

After discovery, virtualization and correlation have built the inventory, a
final **enrichment** stage annotates it in place. Where discovery answers *which
addresses are alive* and service probes answer *what runs on this port*,
enrichment answers *what **is** this host, and what do we already know about it
from other sources* — names from DNS/DHCP, an OS guess, a vendor from the MAC,
and a role + tags.

Each pass is an [`Enricher`](../src/myinventory/enrich/base.py) plugin with its
own registry, mutating the `Inventory` and returning recorded errors (never
raising). The orchestrator runs the enabled passes in a fixed order so each can
build on the previous one's output:

```
snmp → hostname → fingerprint → classify
```

Configure the stage under [`enrichment`](configuration.md#enrichment). The cheap,
dependency-free passes default **on**; SNMP is opt-in and needs the `[snmp]`
extra.

## 1. SNMP (`snmp`) — *ask the device itself*

Many appliances expose little to a port scan but answer SNMP happily. This pass
polls the `system` group (`sysDescr`, `sysName`, `sysObjectID`, `sysContact`,
`sysLocation`) over UDP/161 and records it under `host.extra["snmp"]`. `sysName`
fills a missing hostname; `sysDescr` seeds the OS guess and role classification.

Needs `pip install 'myinventory[snmp]'`. Disabled by default — enable it and set
a community string. When the extra is missing the pass records one note and does
nothing.

## 2. Hostname (`hostname`) — *give IP-only hosts a name*

Two name sources, neither of which overwrites a name a stronger source
(SSH/SNMP) already set:

* **DHCP leases** — parse a dnsmasq `*.leases` or ISC `dhcpd.leases` file you
  point it at, matched back to a host by MAC (preferred) or IP. Runs first
  because the client's own name is usually the most meaningful.
* **Reverse DNS** — a parallel `gethostbyaddr` sweep fills any host still
  missing a name.

## 3. OS fingerprint (`fingerprint`) — *a best-effort guess, not nmap*

Combines three weak signals, most-trusted first: the SNMP `sysDescr`, the
open-port/service profile (RDP+SMB without SSH → Windows; SSH → Unix; only
management ports → an appliance), and the **TTL** of a single ping (initial 64 →
Linux/Unix, 128 → Windows, 255 → network gear). The raw signals always land in
`host.extra["os_fingerprint"]`; the guess only fills `host.os` when nothing
stronger already set it.

## 4. Classification (`classify`) — *the verdict*

Runs last so it can weigh everything above. It produces:

* a **role** (`hypervisor` / `nas` / `network` / `printer` / …), assigned only
  when the current role is still `unknown`/`physical` so a role a backend
  *proved* (VM, hypervisor) is never downgraded; and
* descriptive **tags** (`web-server`, `database`, `ssh`, `vendor:cisco`…), which
  are always additive.

Inputs: service names/products, the OS string, the SNMP `sysDescr`, and the
**MAC OUI vendor** (a small built-in table in
[`oui.py`](../src/myinventory/enrich/oui.py) covering the vendors a homelab
actually meets). User [classification rules](configuration.md#enrichment) run
after the heuristics and, as explicit intent, may override the role.

## Output

Roles drive the shape/colour of each node in the D2 maps; vendor and tags show
up on the host's Markdown page, and `myinventory list` prints the tags inline.
Nothing here changes the data model — names land on `Host.hostname`, the role on
`Host.role`, tags on `Host.tags`, and the supporting evidence in `Host.extra`.
