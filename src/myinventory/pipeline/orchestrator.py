"""The orchestrator runs the scan stages and correlates the results.

Stages, in order:

1. **Host discovery** — run each configured discovery backend over each network.
2. **Service discovery** — run each configured probe over every discovered host.
3. **Virtualization** — run each hypervisor backend; add hypervisor hosts + VMs.
4. **Linux inspection** — for each ``linux_ssh`` target, log in read-only over
   SSH and inventory packages, processes, systemd units and containers.
5. **Correlation** — link VMs to network-discovered hosts and to their
   hypervisor node.

Every plugin call is wrapped so a failure becomes a recorded error instead of an
aborted census.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..config import AppConfig, HypervisorTarget, LinuxSshTarget, NetworkTarget
from ..discovery import DiscoveryResult, get_discovery
from ..models import Host, HostRole, Inventory, Network
from ..services import get_probe
from ..virtualization import BackendResult, get_backend


@dataclass
class ScanReport:
    """Summary of a scan run: what was found and what went wrong."""

    hosts_found: int = 0
    services_found: int = 0
    vms_found: int = 0
    packages_found: int = 0
    containers_found: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        line = (
            f"{self.hosts_found} hosts, {self.services_found} services, "
            f"{self.vms_found} VMs"
        )
        if self.packages_found or self.containers_found:
            line += (
                f", {self.packages_found} packages, "
                f"{self.containers_found} containers"
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
        self._inspect_linux(inventory, report)
        self._correlate(inventory)

        report.hosts_found = len(inventory.hosts)
        report.services_found = sum(len(h.services) for h in inventory.hosts.values())
        report.vms_found = len(inventory.vms)
        report.packages_found = sum(len(h.packages) for h in inventory.hosts.values())
        report.containers_found = sum(
            len(h.containers) for h in inventory.hosts.values()
        )
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

    def _run_backend(self, target: HypervisorTarget) -> BackendResult:
        try:
            return get_backend(target.type).run(target)
        except Exception as exc:  # noqa: BLE001
            return BackendResult(errors=[f"virt/{target.type} @ {target.host}: {exc}"])

    # --- stage 4: linux deep inspection over SSH -------------------------
    def _inspect_linux(self, inventory: Inventory, report: ScanReport) -> None:
        for target in self.config.linux_ssh:
            host, errors = self._inspect_one(target)
            report.errors.extend(errors)
            if host is not None:
                inventory.upsert_host(host)

    @staticmethod
    def _inspect_one(target: LinuxSshTarget) -> tuple[Host | None, list[str]]:
        # Imported lazily so a base install without the [ssh] extra still runs
        # the network/virtualization stages.
        from ..ssh import LinuxInspector, SshTransport

        try:
            transport = SshTransport(target, strict_host_key=target.strict_host_key)
            transport.connect()
        except Exception as exc:  # noqa: BLE001 - fail soft
            return None, [f"ssh/{target.host}: connect failed: {exc}"]
        try:
            inspector = LinuxInspector(transport, target)
            host = inspector.inspect()
            return host, inspector.errors
        except Exception as exc:  # noqa: BLE001 - fail soft
            return None, [f"ssh/{target.host}: inspection failed: {exc}"]
        finally:
            transport.close()

    # --- stage 5: correlation --------------------------------------------
    @staticmethod
    def _correlate(inventory: Inventory) -> None:
        """Cross-link the virtualization view with network discovery.

        * **VM IP ↔ host**: a VM whose guest IP matches a discovered host is
          linked to it; that host learns which hypervisor it runs on and is
          re-classified as a VM (unless it already has a stronger role).
        * **Hypervisor mgmt IP ↔ host node**: handled upstream — the hypervisor
          host is upserted under the same IP-derived ID as the discovered node,
          so the two records merge automatically.
        """
        ip_to_host = {
            addr: host for host in inventory.hosts.values() for addr in host.addresses
        }
        for vm in inventory.vms.values():
            for addr in vm.addresses:
                host = ip_to_host.get(addr)
                if host is not None:
                    vm.host_id = host.id
                    host.hypervisor_id = vm.hypervisor_id
                    if host.role in (HostRole.UNKNOWN, HostRole.PHYSICAL):
                        host.role = HostRole.VM
                    break
