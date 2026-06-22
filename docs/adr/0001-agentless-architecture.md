# ADR 0001 — Agentless discovery

**Status:** Accepted

## Context

We need to inventory hosts, services and VMs across a heterogeneous estate
(physical boxes, appliances, several hypervisors). Two broad approaches exist:
install an agent on every target that reports in, or probe targets from outside.

## Decision

`myinventory` is **agentless**. It discovers via standard network probes
(ICMP/ARP/TCP) and read-only management APIs / SSH where credentials are
provided. Nothing is installed on the targets.

## Consequences

**Positive**

- Works against devices you can't install software on (switches, NAS, printers,
  appliances, other people's VMs).
- Zero target-side maintenance; deploy once, scan anything reachable.
- Lower blast radius — read-only, least-privilege credentials.

**Negative**

- Less depth than an on-host agent (no guaranteed process list without SSH/SNMP
  creds). Mitigated by optional authenticated probes.
- Active scanning generates traffic that IDS will flag and needs authorization
  (see [security.md](../security.md)).
- Some data (e.g. exact guest IPs) depends on guest agents being installed on
  the VMs, which is outside our control.
