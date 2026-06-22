# ADR 0004 — Threads instead of asyncio

**Status:** Accepted

## Context

Discovery and VM enumeration are heavily I/O-bound (thousands of short network
waits). We need concurrency. The two natural choices in Python are `asyncio` and
a thread pool.

## Decision

Use `concurrent.futures.ThreadPoolExecutor` with a bounded, configurable worker
count. No `async`/`await` in the codebase.

## Consequences

**Positive**

- The ecosystem we depend on is **synchronous**: `socket`, `proxmoxer`,
  `pyvmomi`, `libvirt-python`, `paramiko`. Threads use them directly; asyncio
  would force `run_in_executor` wrappers anyway.
- Simpler plugin contract — a backend is a plain method, not a coroutine.
  Lowers the bar for contributors.
- The workload is I/O-bound, so the GIL is not the bottleneck; threads give the
  needed parallelism.

**Negative**

- Thread-pool sizes need tuning for very large scans (exposed as `workers`).
- Shared mutation (merging into the `Inventory`) must stay on the orchestrator
  thread; plugins return data rather than mutating shared state, which we want
  regardless.
