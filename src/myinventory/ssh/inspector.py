"""Drive the read-only command set and assemble a populated :class:`Host`.

The inspector is decoupled from paramiko: it talks to any *runner* exposing
``run(command, *, sudo=False) -> CommandResult``. The real runner is
:class:`~myinventory.ssh.transport.SshTransport`; tests pass a fake that returns
canned outputs. Every command is wrapped so a missing binary or non-zero exit
degrades to a recorded note instead of aborting the inspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..models import DiscoverySource, Host, HostRole, Service
from . import commands as cmd
from . import parsers

if TYPE_CHECKING:
    from ..config import LinuxSshTarget
    from .transport import CommandResult

# Distro IDs (from os-release ID / ID_LIKE) grouped by their package manager.
_DPKG_IDS = {"debian", "ubuntu", "raspbian", "linuxmint", "pop"}
_RPM_IDS = {"rhel", "fedora", "centos", "rocky", "almalinux", "ol", "amzn"}


class Runner(Protocol):
    """The slice of the SSH transport the inspector depends on."""

    def run(self, command: str, *, sudo: bool = False) -> CommandResult: ...


class LinuxInspector:
    """Inspect one Linux host read-only and return an enriched :class:`Host`."""

    def __init__(
        self, runner: Runner, target: LinuxSshTarget, *, top_processes: int = 15
    ) -> None:
        self.runner = runner
        self.target = target
        self.top_processes = top_processes
        self.errors: list[str] = []

    # --- entry point ------------------------------------------------------
    def inspect(self) -> Host:
        host = self._new_host()
        os_id = self._collect_os_facts(host)
        self._collect_packages(host, os_id)
        self._collect_sockets_and_processes(host)
        self._collect_systemd(host)
        self._collect_containers(host)
        return host

    def _new_host(self) -> Host:
        addr = self.target.host
        is_ip = _looks_like_ip(addr)
        return Host(
            id=Host.compute_id(
                address=addr if is_ip else None,
                hostname=self.target.name or (None if is_ip else addr),
            ),
            addresses=[addr] if is_ip else [],
            hostname=self.target.name,
            sources=[DiscoverySource.MANUAL],
        )

    # --- command runner with soft failure --------------------------------
    def _try(
        self,
        command: str,
        *,
        sudo: bool = False,
        optional: bool = False,
        ignore_exit: bool = False,
    ) -> str | None:
        """Run a command, returning its stdout or ``None`` on any failure.

        ``optional=True`` marks a probe for software that is legitimately often
        absent (snap/flatpak, a container runtime). Its failure is expected and
        is *not* recorded as an error, keeping the scan report signal-rich.

        ``ignore_exit=True`` returns stdout even on a non-zero exit — for tools
        like ``systemd-detect-virt`` that signal a *result* ("none") with exit 1.
        """
        try:
            result = self.runner.run(command, sudo=sudo)
        except Exception as exc:  # noqa: BLE001 - never abort the census
            if not optional:
                self.errors.append(f"ssh:{self.target.host}: {command!r} failed: {exc}")
            return None
        if not result.ok and not ignore_exit:
            if not optional:
                self.errors.append(
                    f"ssh:{self.target.host}: {command!r} exit={result.exit_status}"
                )
            return None
        return result.stdout

    # --- stages -----------------------------------------------------------
    def _collect_os_facts(self, host: Host) -> str:
        os_id = ""
        if (text := self._try(cmd.OS_RELEASE)) is not None:
            facts = parsers.parse_os_release(text)
            host.os = facts.get("PRETTY_NAME") or facts.get("NAME") or host.os
            os_id = (facts.get("ID") or "").lower()
            like = (facts.get("ID_LIKE") or "").lower()
            host.extra["os_id"] = os_id
            host.extra["os_id_like"] = like
        if (text := self._try(cmd.UNAME)) is not None:
            host.extra.update(parsers.parse_uname(text))
        if (text := self._try(cmd.UPTIME)) is not None:
            host.extra["uptime"] = text.strip()
        # ``systemd-detect-virt`` exits 1 on bare metal while printing "none";
        # treat that as the answer, not a failure.
        if (text := self._try(cmd.DETECT_VIRT, ignore_exit=True)):
            host.extra["virt"] = text.strip() or "none"
        return os_id or host.extra.get("os_id_like", "")

    def _collect_packages(self, host: Host, os_id: str) -> None:
        ids = set(os_id.split())
        if ids & _DPKG_IDS and (text := self._try(cmd.DPKG)) is not None:
            host.packages.extend(parsers.parse_tabular_packages(text, "dpkg"))
        elif ids & _RPM_IDS and (text := self._try(cmd.RPM)) is not None:
            host.packages.extend(parsers.parse_tabular_packages(text, "rpm"))
        # Universal managers are independent of the base distro; try both,
        # ignoring hosts where they are not installed (commonly absent).
        if (text := self._try(cmd.SNAP, optional=True)) is not None:
            host.packages.extend(parsers.parse_snap(text))
        if (text := self._try(cmd.FLATPAK, optional=True)) is not None:
            host.packages.extend(parsers.parse_flatpak(text))
        host.extra["package_count"] = len(host.packages)

    def _collect_sockets_and_processes(self, host: Host) -> None:
        sockets = []
        if (text := self._try(cmd.SS, sudo=self.target.sudo)) is not None:
            sockets = parsers.parse_ss(text)

        if (text := self._try(cmd.PS)) is not None:
            host.processes = parsers.parse_ps(text)[: self.top_processes]

        # Enrich services with their owning process; record which processes
        # listen on which port so the host page can show the mapping.
        proc_by_name = {p.name: p for p in host.processes}
        for sock in sockets:
            if sock["proto"] != "tcp":
                continue
            self._attach_socket_service(host, sock)
            name, port = sock.get("process"), sock["port"]
            if name and name in proc_by_name and port not in proc_by_name[name].listening_ports:
                proc_by_name[name].listening_ports.append(port)

    @staticmethod
    def _attach_socket_service(host: Host, sock: dict) -> None:
        key = f"tcp/{sock['port']}"
        existing = next((s for s in host.services if s.key == key), None)
        svc = existing or Service(port=sock["port"], protocol="tcp")
        if sock.get("process") and not svc.product:
            svc.product = sock["process"]
        if not svc.name:
            svc.name = sock.get("process")
        svc.source = svc.source or "ssh-inspect"
        if sock.get("pid"):
            svc.extra["pid"] = sock["pid"]
        host.add_service(svc)

    def _collect_systemd(self, host: Host) -> None:
        if (text := self._try(cmd.SYSTEMCTL)) is not None:
            host.extra["systemd_units"] = parsers.parse_systemd_units(text)

    def _collect_containers(self, host: Host) -> None:
        for runtime in ("docker", "podman"):
            version_cmd = cmd.RUNTIME_VERSION.format(rt=runtime)
            if self._try(version_cmd, optional=True) is None:
                continue  # runtime not installed — expected, stay quiet
            # The runtime is installed; listing it usually needs privilege.
            ps_cmd = cmd.RUNTIME_PS.format(rt=runtime)
            text = self._try(ps_cmd, sudo=self.target.sudo, optional=True)
            if text is None:
                self.errors.append(
                    f"ssh:{self.target.host}: {runtime} present but listing "
                    f"failed — {self._runtime_hint()}"
                )
                continue
            containers = parsers.parse_docker_ps(text, runtime)
            host.containers.extend(containers)
            self._map_container_ports(host, containers)
            if host.role == HostRole.UNKNOWN and containers:
                host.extra["container_runtime"] = runtime
            return  # first working runtime wins

    def _runtime_hint(self) -> str:
        """Tailor the 'cannot list containers' hint to the session's privilege."""
        if self.target.username == "root" or self.target.sudo:
            # Already privileged — the daemon/socket is the likely problem.
            return "is the daemon running and the socket accessible?"
        return "insufficient privilege? (try setting 'sudo: true')"

    @staticmethod
    def _map_container_ports(host: Host, containers: list) -> None:
        """Link a container's published host ports to the host's services."""
        for container in containers:
            for port in container.published_ports:
                key = f"tcp/{port}"
                svc = next((s for s in host.services if s.key == key), None)
                if svc is None:
                    svc = Service(port=port, protocol="tcp", source="docker")
                    host.add_service(svc)
                if not svc.product and container.image:
                    svc.product = container.image
                svc.extra["container"] = container.name


def _looks_like_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)
