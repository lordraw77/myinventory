"""The orchestrator runs the scan stages and correlates the results.

Stages, in order:

1. **Host discovery** — run each configured discovery backend over each network.
2. **Service discovery** — run each configured probe over every discovered host.
3. **Virtualization** — run each hypervisor backend; add hypervisor hosts + VMs.
4. **Correlation** — link VMs to network-discovered hosts and to their
   hypervisor node.

Every plugin call is wrapped so a failure becomes a recorded error instead of an
aborted census.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List

from ..config import AppConfig, HypervisorTarget, NetworkTarget
from ..discovery import DiscoveryResult, get_discovery
from ..models import Inventory, Network
from ..services import get_probe
from ..virtualization import get_backend


@dataclass
class ScanReport:
    """Summary of a scan run: what was found and what went wrong."""

    hosts_found: int = 0
    services_found: int = 0
    vms_found: int = 0
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        line = (
            f"{self.hosts_found} hosts, {self.services_found} services, "
            f"{self.vms_found} VMs"
        )
        if self.errors:
            line += f" ({len(self.errors)} errors)"
        return line


class Orchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def scan(self) -> tuple[Inventory, ScanReport]:
        inventory = Inventory()
        report = ScanReport()

        self._discover_hosts(inventory, report)
        self._probe_services(inventory, report)
        self._collect_virtualization(inventory, report)
        self._correlate(inventory)

        report.hosts_found = len(inventory.hosts)
        report.services_found = sum(len(h.services) for h in inventory.hosts.values())
        report.vms_found = len(inventory.vms)
        return inventory, report

    # --- stage 1: host discovery -----------------------------------------
    def _discover_hosts(self, inventory: Inventory, report: ScanReport) -> None:
        for target in self.config.networks:
            inventory.add_network(
                Network(cidr=target.cidr, name=target.name, vlan=target.vlan)
            )
            for backend_name in target.discovery:
                result = self._run_discovery(backend_name, target)
                report.errors.extend(result.errors)
                for host in result.hosts:
                    inventory.upsert_host(host)

    def _run_discovery(self, name: str, target: NetworkTarget) -> DiscoveryResult:
        try:
            return get_discovery(name).discover(target)
        except Exception as exc:  # noqa: BLE001 - fail soft
            return DiscoveryResult(errors=[f"discovery/{name} on {target.cidr}: {exc}"])

    # --- stage 2: service discovery --------------------------------------
    def _probe_services(self, inventory: Inventory, report: ScanReport) -> None:
        hosts = list(inventory.hosts.values())
        for probe_name in self.config.service_probes:
            try:
                probe = get_probe(probe_name)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"probe/{probe_name}: {exc}")
                continue

            with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
                for host, services in zip(hosts, pool.map(probe.probe, hosts)):
                    for svc in services:
                        host.add_service(svc)

    # --- stage 3: virtualization -----------------------------------------
    def _collect_virtualization(self, inventory: Inventory, report: ScanReport) -> None:
        for target in self.config.hypervisors:
            result = self._run_backend(target)
            report.errors.extend(result.errors)
            for host in result.hosts:
                inventory.upsert_host(host)
            for vm in result.vms:
                inventory.upsert_vm(vm)

    def _run_backend(self, target: HypervisorTarget):
        try:
            return get_backend(target.type).run(target)
        except Exception as exc:  # noqa: BLE001
            from ..virtualization import BackendResult

            return BackendResult(errors=[f"virt/{target.type} @ {target.host}: {exc}"])

    # --- stage 4: correlation --------------------------------------------
    @staticmethod
    def _correlate(inventory: Inventory) -> None:
        """Link each VM to a network-discovered host sharing one of its IPs."""
        ip_to_host = {
            addr: host for host in inventory.hosts.values() for addr in host.addresses
        }
        for vm in inventory.vms.values():
            for addr in vm.addresses:
                host = ip_to_host.get(addr)
                if host is not None:
                    vm.host_id = host.id
                    host.hypervisor_id = vm.hypervisor_id
                    break
