# Contributing

## Development setup

```bash
git clone <repo> && cd myinventory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,all]"

pytest            # tests (run without network access)
ruff check src    # lint
mypy              # type-check
```

The model, storage and renderers are fully unit-tested against
[`tests/fixtures/inventory.json`](../tests/fixtures/inventory.json) — no network
needed. New plugins should ship with a fixture-driven test too.

## Project conventions

- Python ≥3.9, `from __future__ import annotations` in every module.
- Plain `dataclasses` for the model; no ORM, no heavy frameworks in core.
- Optional third-party SDKs (scapy, pyvmomi, libvirt, proxmoxer) are imported
  **inside** the backend module that needs them, never at package top level, so
  a base install stays importable.
- Fail soft: a backend error is a recorded `*.errors` entry, never an exception
  that aborts the run.

## Writing a discovery backend

```python
# src/myinventory/discovery/icmp.py
from ..models import DiscoverySource, Host
from .base import DiscoveryResult, HostDiscovery, register_discovery

@register_discovery("icmp")
class IcmpDiscovery(HostDiscovery):
    def discover(self, target) -> DiscoveryResult:
        result = DiscoveryResult()
        # ... ping sweep target.cidr ...
        # result.hosts.append(Host(id=Host.compute_id(address=ip),
        #                          addresses=[ip], sources=[DiscoverySource.ICMP]))
        return result
```

Then reference it in config: `discovery: [icmp]`.

## Writing a service probe

```python
from ..base import ServiceProbe, register_probe
from ...models import Host, Service

@register_probe("ssh")
class SshProbe(ServiceProbe):
    def probe(self, host: Host) -> list[Service]:
        # connect with paramiko, read package versions, return Service objects
        ...
```

Register the module so the side-effect import runs — add it to
`services/probes/__init__.py`.

## Writing a virtualization backend

```python
from ..models import Host, HostRole, PowerState, VirtualMachine
from .base import BackendResult, VirtualizationBackend, register_backend

@register_backend("hyperv")
class HyperVBackend(VirtualizationBackend):
    def connect(self, target) -> None:
        from some_hyperv_sdk import Client   # lazy, optional import
        self._client = Client(target.host, ...)

    def collect(self, target) -> BackendResult:
        result = BackendResult()
        # build the hypervisor Host + its VirtualMachine list
        return result

    def close(self) -> None:
        ...
```

Add it to the side-effect imports in `virtualization/__init__.py`. The
orchestrator calls `run()` (connect → collect → close, errors captured) — you
don't wire it up anywhere else.

## Writing a renderer

A renderer is a class with `render(inventory, out_dir) -> List[Path]` and no
side effects beyond writing files. Keep it dumb: all correlation/enrichment
happens in the pipeline, so a renderer only formats what it is given.

## Pull-request checklist

- [ ] Tests pass; new behavior has a test.
- [ ] `ruff` and `mypy` are clean.
- [ ] Optional deps are imported lazily inside the backend.
- [ ] Docs updated (this `docs/` tree) when behavior or config changes.
- [ ] An ADR added under `docs/adr/` for a significant design decision.
