# ADR 0002 — Plugin registries for backends

**Status:** Accepted

## Context

There are many discovery methods, service probes and hypervisor types, and the
set will keep growing (Hyper-V, cloud, k8s…). Several backends need heavy
optional dependencies (`pyvmomi`, `libvirt-python`, `scapy`) that we don't want
in a base install.

## Decision

Each of the three extension surfaces (discovery, service probes, virtualization)
has a **string-keyed registry** populated by a `@register_*("name")` decorator.
Config selects backends by key; the orchestrator looks them up and never imports
a concrete backend directly. Each backend imports its third-party SDK **lazily,
inside its own module**.

## Consequences

**Positive**

- Adding a backend is "write a class, decorate it, add a side-effect import" —
  no core changes.
- Optional heavy deps stay isolated: a base install without `[virt]`/`[scan]`
  still imports and runs the reference backends.
- Config stays declarative (`type: proxmox`) with no Python wiring.

**Negative**

- Side-effect imports (to trigger registration) are slightly implicit; mitigated
  by centralizing them in each package's `__init__.py`.
- A typo'd backend key fails at run time, not import time; mitigated by
  `validate-config` and a clear "available: …" error message.
