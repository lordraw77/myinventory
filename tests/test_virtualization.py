"""Tests for the Milestone 2 virtualization backends and correlation.

These exercise the backends without any live hypervisor: the SDK-specific
collection logic is factored into pure helpers, and ``collect()`` is driven with
small hand-rolled fakes that mimic the proxmoxer / libvirt object shapes.
"""

from __future__ import annotations

from types import SimpleNamespace

from myinventory.config import HypervisorTarget
from myinventory.models import HostRole, Inventory, PowerState, VirtualMachine
from myinventory.pipeline.orchestrator import Orchestrator
from myinventory.virtualization import available, get_backend
from myinventory.virtualization import libvirt as lv
from myinventory.virtualization import proxmox as px
from myinventory.virtualization import vmware as vm


def test_all_backends_registered() -> None:
    assert set(available()) == {"proxmox", "libvirt", "vmware"}
    assert isinstance(get_backend("libvirt"), lv.LibvirtBackend)


# --- proxmox --------------------------------------------------------------
def test_proxmox_ips_from_agent_drops_loopback() -> None:
    payload = {
        "result": [
            {
                "name": "lo",
                "hardware-address": "00:00:00:00:00:00",
                "ip-addresses": [{"ip-address": "127.0.0.1"}],
            },
            {
                "name": "eth0",
                "hardware-address": "AA:BB:CC:00:00:01",
                "ip-addresses": [
                    {"ip-address": "192.168.1.50"},
                    {"ip-address": "fe80::1"},
                ],
            },
        ]
    }
    ips, macs = px._ips_from_agent(payload)
    assert ips == ["192.168.1.50"]
    assert macs == ["aa:bb:cc:00:00:01"]  # all-zero MAC dropped, normalized


def test_proxmox_ips_from_lxc_config() -> None:
    config = {
        "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:00:00:02,ip=192.168.1.60/24",
        "net1": "name=eth1,bridge=vmbr1,hwaddr=AA:BB:CC:00:00:03,ip=dhcp",
        "rootfs": "local-lvm:vm-200-disk-0",  # ignored, not a netN key
    }
    ips, macs = px._ips_from_lxc_config(config)
    assert ips == ["192.168.1.60"]  # dhcp interface contributes no static IP
    assert macs == ["aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03"]


def test_proxmox_split_tags() -> None:
    assert px._split_tags("prod;web") == ["prod", "web"]
    assert px._split_tags(None) == []


class _FakeApi:
    """Recursive fake of a proxmoxer client driven by a path → result map."""

    def __init__(self, responses: dict[tuple, object], path: tuple = ()) -> None:
        self._responses = responses
        self._path = path

    def __getattr__(self, name: str):  # noqa: ANN204 - test helper
        if name == "get":
            return lambda: self._responses[self._path]
        return _FakeApi(self._responses, self._path + (name,))

    def __call__(self, *args: object) -> "_FakeApi":
        return _FakeApi(self._responses, self._path + args)


def test_proxmox_collect_end_to_end() -> None:
    responses = {
        ("nodes",): [{"node": "pve1"}],
        ("nodes", "pve1", "qemu"): [
            {
                "vmid": 100,
                "name": "web",
                "status": "running",
                "cpus": 2,
                "maxmem": 2 * 1024**3,
                "maxdisk": 32 * 1024**3,
                "tags": "prod;web",
            }
        ],
        ("nodes", "pve1", "lxc"): [
            {"vmid": 200, "name": "ct1", "status": "running", "cpus": 1,
             "maxmem": 512 * 1024**2}
        ],
        ("nodes", "pve1", "qemu", 100, "agent", "network-get-interfaces"): {
            "result": [
                {
                    "name": "eth0",
                    "hardware-address": "aa:bb:cc:00:00:01",
                    "ip-addresses": [{"ip-address": "192.168.1.50"}],
                }
            ]
        },
        ("nodes", "pve1", "lxc", 200, "config"): {
            "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:00:00:02,ip=192.168.1.60/24",
        },
    }
    backend = px.ProxmoxBackend()
    backend._api = _FakeApi(responses)
    target = HypervisorTarget(type="proxmox", host="192.168.1.10")

    result = backend.collect(target)

    assert len(result.hosts) == 1
    hyper = result.hosts[0]
    assert hyper.id == "ip:192.168.1.10"
    assert hyper.role == HostRole.HYPERVISOR
    assert len(hyper.hosted_vm_ids) == 2

    by_name = {v.name: v for v in result.vms}
    assert by_name["web"].addresses == ["192.168.1.50"]
    assert by_name["web"].memory_mb == 2048
    assert by_name["web"].disk_gb == 32.0
    assert by_name["web"].tags == ["prod", "web"]
    assert by_name["ct1"].addresses == ["192.168.1.60"]


# --- libvirt --------------------------------------------------------------
def test_libvirt_power_state_mapping() -> None:
    assert lv._power_state_from_code(1) == PowerState.RUNNING
    assert lv._power_state_from_code(5) == PowerState.STOPPED
    assert lv._power_state_from_code(3) == PowerState.PAUSED
    assert lv._power_state_from_code(99) == PowerState.UNKNOWN


def test_libvirt_ips_from_interface_addresses() -> None:
    ifaces = {
        "lo": {"name": "lo", "hwaddr": "00:00:00:00:00:00",
               "addrs": [{"addr": "127.0.0.1", "type": 0}]},
        "eth0": {"name": "eth0", "hwaddr": "52:54:00:AA:BB:CC",
                 "addrs": [{"addr": "10.0.0.5", "type": 0},
                           {"addr": "fe80::5", "type": 1}]},
    }
    ips, macs = lv._ips_from_interface_addresses(ifaces)
    assert ips == ["10.0.0.5"]
    assert macs == ["52:54:00:aa:bb:cc"]


def test_libvirt_host_from_uri() -> None:
    assert lv._host_from_uri("qemu+ssh://root@192.168.1.30/system") == "192.168.1.30"
    assert lv._host_from_uri("qemu:///system") is None


class _FakeDomain:
    def __init__(self, uuid: str, name: str, state: int, ifaces: dict) -> None:
        self._uuid, self._name, self._state, self._ifaces = uuid, name, state, ifaces

    def UUIDString(self) -> str:  # noqa: N802 - mirror libvirt API
        return self._uuid

    def name(self) -> str:
        return self._name

    def info(self) -> tuple:
        # (state, maxMem KiB, mem KiB, nrVirtCpu, cpuTime)
        return (self._state, 2 * 1024 * 1024, 2 * 1024 * 1024, 4, 0)

    def interfaceAddresses(self, source: int, flags: int) -> dict:  # noqa: N802
        return self._ifaces


class _FakeConn:
    def __init__(self, domains: list) -> None:
        self._domains = domains

    def getHostname(self) -> str:  # noqa: N802 - mirror libvirt API
        return "kvm-host"

    def listAllDomains(self) -> list:  # noqa: N802
        return self._domains


def test_libvirt_collect_end_to_end() -> None:
    dom = _FakeDomain(
        uuid="abcd-1234",
        name="vm1",
        state=1,
        ifaces={"eth0": {"name": "eth0", "hwaddr": "52:54:00:00:00:01",
                         "addrs": [{"addr": "10.0.0.9", "type": 0}]}},
    )
    backend = lv.LibvirtBackend()
    backend._conn = _FakeConn([dom])
    target = HypervisorTarget(type="libvirt", host="qemu+ssh://root@192.168.1.30/system")

    result = backend.collect(target)

    assert len(result.hosts) == 1
    hyper = result.hosts[0]
    assert hyper.addresses == ["192.168.1.30"]
    assert hyper.hostname == "kvm-host"
    assert len(result.vms) == 1
    vmrec = result.vms[0]
    assert vmrec.id == "libvirt:abcd-1234"
    assert vmrec.power_state == PowerState.RUNNING
    assert vmrec.vcpus == 4
    assert vmrec.memory_mb == 2048
    assert vmrec.addresses == ["10.0.0.9"]
    assert hyper.hosted_vm_ids == [vmrec.id]


# --- vmware ---------------------------------------------------------------
def test_vmware_power_state_mapping() -> None:
    assert vm._power_state_from_state("poweredOn") == PowerState.RUNNING
    assert vm._power_state_from_state("poweredOff") == PowerState.STOPPED
    assert vm._power_state_from_state("suspended") == PowerState.PAUSED
    assert vm._power_state_from_state("weird") == PowerState.UNKNOWN


def test_vmware_ips_from_guest_net() -> None:
    nics = [
        SimpleNamespace(macAddress="00:50:56:AA:BB:CC",
                        ipAddress=["172.16.0.4", "fe80::4", "127.0.0.1"]),
        SimpleNamespace(macAddress="00:50:56:AA:BB:CD", ipAddress=None),
    ]
    ips, macs = vm._ips_from_guest_net(nics)
    assert ips == ["172.16.0.4"]
    assert macs == ["00:50:56:aa:bb:cc", "00:50:56:aa:bb:cd"]


def test_vmware_vm_to_record() -> None:
    fake = SimpleNamespace(
        summary=SimpleNamespace(
            config=SimpleNamespace(
                name="app01",
                instanceUuid="uuid-1",
                uuid="bios-1",
                numCpu=4,
                memorySizeMB=8192,
                guestFullName="Ubuntu Linux (64-bit)",
            ),
            runtime=SimpleNamespace(powerState="poweredOn"),
        ),
        guest=SimpleNamespace(
            net=[SimpleNamespace(macAddress="00:50:56:00:00:01",
                                 ipAddress=["172.16.0.10"])]
        ),
        resourcePool=SimpleNamespace(name="prod-pool"),
    )
    record = vm.VMwareBackend._vm_to_record(fake, "vmware:esxi1")

    assert record.id == "vmware:uuid-1"
    assert record.name == "app01"
    assert record.vcpus == 4
    assert record.memory_mb == 8192
    assert record.guest_os == "Ubuntu Linux (64-bit)"
    assert record.power_state == PowerState.RUNNING
    assert record.addresses == ["172.16.0.10"]
    assert record.extra["resource_pool"] == "prod-pool"


# --- correlation ----------------------------------------------------------
def test_correlation_links_vm_to_discovered_host() -> None:
    from myinventory.models import DiscoverySource, Host

    inv = Inventory()
    hyper = Host(id="ip:192.168.1.10", addresses=["192.168.1.10"],
                 role=HostRole.HYPERVISOR)
    guest_host = Host(id="ip:192.168.1.50", addresses=["192.168.1.50"],
                      role=HostRole.UNKNOWN, sources=[DiscoverySource.TCP])
    inv.upsert_host(hyper)
    inv.upsert_host(guest_host)
    inv.upsert_vm(VirtualMachine(
        id="proxmox:pve1:100", name="web", hypervisor_id=hyper.id,
        backend="proxmox", addresses=["192.168.1.50"],
    ))

    Orchestrator._correlate(inv)

    web = inv.vms["proxmox:pve1:100"]
    assert web.host_id == "ip:192.168.1.50"
    assert inv.hosts["ip:192.168.1.50"].hypervisor_id == hyper.id
    assert inv.hosts["ip:192.168.1.50"].role == HostRole.VM  # reclassified
