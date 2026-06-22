"""Tests for Milestone 3 — agentless Linux deep inspection over SSH.

The SSH transport is never opened: parsers are tested against captured output,
and the inspector runs end-to-end against a fake runner returning canned command
results — the same decoupling the in-process TCP lab uses for discovery.
"""

from __future__ import annotations

import pytest

from myinventory.config import LinuxSshTarget
from myinventory.models import Container, Host, HostRole, Inventory
from myinventory.ssh import UnsafeCommandError, assert_read_only
from myinventory.ssh import commands as cmd
from myinventory.ssh import parsers
from myinventory.ssh.inspector import LinuxInspector
from myinventory.ssh.transport import CommandResult


# --- parsers --------------------------------------------------------------
def test_parse_os_release() -> None:
    text = (
        'NAME="Ubuntu"\n'
        'VERSION="22.04.3 LTS (Jammy Jellyfish)"\n'
        "ID=ubuntu\n"
        'ID_LIKE=debian\n'
        'PRETTY_NAME="Ubuntu 22.04.3 LTS"\n'
    )
    facts = parsers.parse_os_release(text)
    assert facts["ID"] == "ubuntu"
    assert facts["PRETTY_NAME"] == "Ubuntu 22.04.3 LTS"


def test_parse_uname() -> None:
    u = parsers.parse_uname("Linux 5.15.0-86-generic x86_64")
    assert u == {"kernel": "Linux", "kernel_release": "5.15.0-86-generic",
                 "arch": "x86_64"}


def test_parse_tabular_packages() -> None:
    pkgs = parsers.parse_tabular_packages("bash\t5.1-6ubuntu1\nnginx\t1.25.3-1\n", "dpkg")
    assert [(p.name, p.version, p.manager) for p in pkgs] == [
        ("bash", "5.1-6ubuntu1", "dpkg"),
        ("nginx", "1.25.3-1", "dpkg"),
    ]


def test_parse_snap_skips_header() -> None:
    text = "Name  Version  Rev  Tracking  Publisher  Notes\ncore20  20230801  2015  latest/stable  canonical  base\n"
    pkgs = parsers.parse_snap(text)
    assert len(pkgs) == 1
    assert pkgs[0].name == "core20" and pkgs[0].manager == "snap"


def test_parse_ss_extracts_port_and_process() -> None:
    text = (
        'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=789,fd=3))\n'
        'tcp LISTEN 0 511 *:80 *:* users:(("nginx",pid=1011,fd=6),("nginx",pid=1010,fd=6))\n'
        'udp UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=512,fd=12))\n'
    )
    socks = parsers.parse_ss(text)
    by_port = {s["port"]: s for s in socks}
    assert by_port[22]["process"] == "sshd" and by_port[22]["pid"] == 789
    assert by_port[80]["process"] == "nginx"
    assert by_port[53]["proto"] == "udp"


def test_parse_ps() -> None:
    text = "789 root 0.1 4096 sshd\n1011 www-data 2.5 81920 nginx\nbad line here\n"
    procs = parsers.parse_ps(text)
    assert [(p.pid, p.name, p.user, p.rss_kb) for p in procs] == [
        (789, "sshd", "root", 4096),
        (1011, "nginx", "www-data", 81920),
    ]
    assert procs[1].cpu_percent == 2.5


def test_parse_systemd_units() -> None:
    text = (
        "ssh.service loaded active running OpenBSD Secure Shell server\n"
        "nginx.service loaded active running A high performance web server\n"
        "something.mount loaded active mounted /boot\n"
    )
    assert parsers.parse_systemd_units(text) == ["ssh.service", "nginx.service"]


def test_parse_docker_ps_docker_shape() -> None:
    line = (
        '{"ID":"abc123def456","Names":"web-1","Image":"nginx:1.25",'
        '"State":"running","Ports":"0.0.0.0:8080->80/tcp",'
        '"Labels":"com.docker.compose.project=myapp,maintainer=ops"}'
    )
    [c] = parsers.parse_docker_ps(line, "docker")
    assert c.id == "abc123def456"[:12]
    assert c.name == "web-1"
    assert c.image == "nginx:1.25"
    assert c.state == "running"
    assert c.compose_project == "myapp"
    assert c.published_ports == [8080]


def test_parse_docker_ps_podman_list_shapes() -> None:
    # Podman emits Names/Ports as lists and "Up ..." style status.
    line = '{"Id":"f00","Names":["api"],"Image":"alpine","State":"running","Ports":["0.0.0.0:9000->9000/tcp"]}'
    [c] = parsers.parse_docker_ps(line, "podman")
    assert c.name == "api"
    assert c.runtime == "podman"
    assert c.published_ports == [9000]


def test_container_published_ports_ignores_unmapped() -> None:
    c = Container(id="x", name="x", ports=["80/tcp", "0.0.0.0:8080->80/tcp"])
    assert c.published_ports == [8080]


# --- safety allow-list ----------------------------------------------------
def test_assert_read_only_accepts_real_commands() -> None:
    for command in (cmd.OS_RELEASE, cmd.SS, cmd.PS, cmd.SYSTEMCTL,
                    cmd.RUNTIME_PS.format(rt="docker")):
        assert_read_only(command)  # must not raise


@pytest.mark.parametrize("bad", [
    "cat /etc/shadow; rm -rf /",
    "ss -tulpn | grep 22",
    "curl http://evil",          # binary not on the allow-list
    "cat /etc/os-release > /tmp/x",
    "rpm -qa && reboot",
])
def test_assert_read_only_rejects_unsafe(bad: str) -> None:
    with pytest.raises(UnsafeCommandError):
        assert_read_only(bad)


# --- inspector end-to-end (fake runner) -------------------------------------
class _FakeRunner:
    """Returns canned output keyed by exact command; unknown → 'not found'.

    A response value may be a plain stdout string (exit 0) or a
    ``(stdout, exit_status)`` tuple to simulate a non-zero exit.
    """

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses

    def run(self, command: str, *, sudo: bool = False) -> CommandResult:
        if command in self._responses:
            value = self._responses[command]
            if isinstance(value, tuple):
                stdout, status = value
                return CommandResult(command, stdout=stdout, exit_status=status)
            return CommandResult(command, stdout=str(value))
        return CommandResult(command, stderr="not found", exit_status=127)


def _ubuntu_docker_host() -> dict[str, str]:
    return {
        cmd.OS_RELEASE: 'ID=ubuntu\nPRETTY_NAME="Ubuntu 22.04.3 LTS"\n',
        cmd.UNAME: "Linux 5.15.0-86-generic x86_64",
        cmd.UPTIME: "up 3 days, 4 hours",
        cmd.DETECT_VIRT: "kvm",
        cmd.DPKG: "bash\t5.1-6ubuntu1\nnginx\t1.25.3-1\n",
        cmd.SS: (
            'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=789,fd=3))\n'
            'tcp LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("docker-proxy",pid=1011,fd=4))\n'
        ),
        cmd.PS: "789 root 0.1 4096 sshd\n1011 root 0.5 8000 docker-proxy\n",
        cmd.SYSTEMCTL: "ssh.service loaded active running OpenBSD Secure Shell server\n",
        cmd.RUNTIME_VERSION.format(rt="docker"): "Docker version 24.0.7",
        cmd.RUNTIME_PS.format(rt="docker"): (
            '{"ID":"abc123","Names":"web-1","Image":"nginx:1.25",'
            '"State":"running","Ports":"0.0.0.0:8080->80/tcp",'
            '"Labels":"com.docker.compose.project=myapp"}'
        ),
    }


def test_inspector_builds_full_host() -> None:
    target = LinuxSshTarget(host="192.168.1.20", name="app-1")
    inspector = LinuxInspector(_FakeRunner(_ubuntu_docker_host()), target)

    host = inspector.inspect()

    assert host.id == "ip:192.168.1.20"
    assert host.os == "Ubuntu 22.04.3 LTS"
    assert host.extra["kernel_release"] == "5.15.0-86-generic"
    assert host.extra["arch"] == "x86_64"
    assert host.extra["virt"] == "kvm"

    # packages
    assert {p.name for p in host.packages} == {"bash", "nginx"}
    assert all(p.manager == "dpkg" for p in host.packages)

    # sockets enriched services + process listening ports
    svc22 = next(s for s in host.services if s.port == 22)
    assert svc22.product == "sshd" and svc22.extra["pid"] == 789
    sshd = next(p for p in host.processes if p.name == "sshd")
    assert sshd.listening_ports == [22]

    # systemd
    assert host.extra["systemd_units"] == ["ssh.service"]

    # containers + published-port → service mapping
    assert len(host.containers) == 1
    web = host.containers[0]
    assert web.name == "web-1" and web.compose_project == "myapp"
    svc8080 = next(s for s in host.services if s.port == 8080)
    assert svc8080.extra["container"] == "web-1"


def test_inspector_degrades_when_commands_missing() -> None:
    # Only os-release answers; everything else is "not found".
    target = LinuxSshTarget(host="10.0.0.9")
    responses = {cmd.OS_RELEASE: "ID=rocky\nPRETTY_NAME=\"Rocky Linux 9\"\n"}
    inspector = LinuxInspector(_FakeRunner(responses), target)

    host = inspector.inspect()

    assert host.os == "Rocky Linux 9"
    assert host.packages == [] and host.containers == []
    assert inspector.errors  # missing commands were recorded, not raised


def test_optional_probes_do_not_pollute_errors() -> None:
    # A healthy Debian host with no snap/flatpak/docker: those absences are
    # expected and must not show up as errors.
    target = LinuxSshTarget(host="10.0.0.5")
    responses = {
        cmd.OS_RELEASE: 'ID=debian\nPRETTY_NAME="Debian 12"\n',
        cmd.UNAME: "Linux 6.1.0 x86_64",
        cmd.UPTIME: "up 1 day",
        cmd.DETECT_VIRT: "none",
        cmd.DPKG: "bash\t5.2\n",
        cmd.SS: 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))',
        cmd.PS: "1 root 0.0 1000 sshd",
        cmd.SYSTEMCTL: "ssh.service loaded active running x",
    }
    inspector = LinuxInspector(_FakeRunner(responses), target)
    inspector.inspect()

    # snap/flatpak/docker/podman were all absent but stayed silent.
    assert inspector.errors == []


def test_container_runtime_unlistable_hints_sudo_for_unprivileged() -> None:
    # Non-root, no sudo → the hint nudges towards enabling sudo.
    target = LinuxSshTarget(host="10.0.0.6", username="ops", sudo=False)
    responses = {
        cmd.OS_RELEASE: "ID=debian\n",
        cmd.RUNTIME_VERSION.format(rt="docker"): "Docker version 24",
        # docker ps deliberately absent → exit 127.
    }
    inspector = LinuxInspector(_FakeRunner(responses), target)
    inspector.inspect()

    assert any("try setting 'sudo: true'" in e for e in inspector.errors)


def test_detect_virt_exit1_means_none_not_an_error() -> None:
    # systemd-detect-virt prints "none" and exits 1 on bare metal.
    target = LinuxSshTarget(host="10.0.0.8")
    responses = {
        cmd.OS_RELEASE: "ID=debian\n",
        cmd.DETECT_VIRT: ("none\n", 1),
    }
    inspector = LinuxInspector(_FakeRunner(responses), target)
    host = inspector.inspect()

    assert host.extra["virt"] == "none"
    assert not any("detect-virt" in e for e in inspector.errors)


def test_container_runtime_unlistable_hints_daemon_for_root() -> None:
    # Already root → sudo wouldn't help, so the hint points at the daemon.
    target = LinuxSshTarget(host="10.0.0.7", username="root")
    responses = {
        cmd.OS_RELEASE: "ID=debian\n",
        cmd.RUNTIME_VERSION.format(rt="docker"): "Docker version 24",
    }
    inspector = LinuxInspector(_FakeRunner(responses), target)
    inspector.inspect()

    assert any("daemon running" in e for e in inspector.errors)


# --- model round-trip -----------------------------------------------------
def test_host_software_round_trip() -> None:
    inv = Inventory()
    target = LinuxSshTarget(host="192.168.1.20", name="app-1")
    host = LinuxInspector(_FakeRunner(_ubuntu_docker_host()), target).inspect()
    host.role = HostRole.PHYSICAL
    inv.upsert_host(host)

    again = Inventory.from_json(inv.to_json())
    restored: Host = again.hosts[host.id]
    assert [p.name for p in restored.packages] == [p.name for p in host.packages]
    assert restored.containers[0].name == "web-1"
    assert restored.processes[0].pid == host.processes[0].pid
