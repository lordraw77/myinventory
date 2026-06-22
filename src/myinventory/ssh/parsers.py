"""Pure parsers for the read-only commands the Linux inspector runs.

Every function here turns raw command output into model records (or plain
dicts). They contain no I/O, so they are unit-tested directly against captured
fixtures — the SSH transport is mocked out entirely.
"""

from __future__ import annotations

import json
import re

from ..models import Container, Package, Process


# --- OS facts -------------------------------------------------------------
def parse_os_release(text: str) -> dict[str, str]:
    """Parse ``/etc/os-release`` (``KEY="value"`` lines) into a dict."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def parse_uname(text: str) -> dict[str, str]:
    """Parse ``uname -srm`` → kernel name, release and machine architecture."""
    parts = text.split()
    return {
        "kernel": parts[0] if parts else "",
        "kernel_release": parts[1] if len(parts) > 1 else "",
        "arch": parts[2] if len(parts) > 2 else "",
    }


# --- packages -------------------------------------------------------------
def parse_tabular_packages(text: str, manager: str) -> list[Package]:
    """Parse tab-separated ``name<TAB>version`` output (dpkg / rpm)."""
    packages: list[Package] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, _, version = line.partition("\t")
        name = name.strip()
        if name:
            packages.append(Package(name=name, version=version.strip() or None,
                                    manager=manager))
    return packages


def parse_snap(text: str) -> list[Package]:
    """Parse ``snap list`` output (whitespace columns, with a header row)."""
    packages: list[Package] = []
    for i, line in enumerate(text.splitlines()):
        if i == 0 and line.lower().startswith("name"):
            continue  # header
        cols = line.split()
        if len(cols) >= 2:
            packages.append(Package(name=cols[0], version=cols[1], manager="snap"))
    return packages


def parse_flatpak(text: str) -> list[Package]:
    """Parse ``flatpak list --columns=application,version`` (tab-separated)."""
    packages: list[Package] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        name = cols[0].strip()
        if name:
            version = cols[1].strip() if len(cols) > 1 else None
            packages.append(Package(name=name, version=version or None,
                                    manager="flatpak"))
    return packages


# --- listening sockets ----------------------------------------------------
_SS_PROC = re.compile(r'\("(?P<name>[^"]+)",pid=(?P<pid>\d+)')


def parse_ss(text: str) -> list[dict]:
    """Parse ``ss -H -tulpn`` into ``{proto, port, process, pid}`` entries.

    Example line::

        tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=789,fd=3))
    """
    sockets: list[dict] = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        proto = cols[0]
        local = cols[4]
        port = _port_from_addr(local)
        if port is None:
            continue
        proc = _SS_PROC.search(line)
        sockets.append({
            "proto": proto,
            "port": port,
            "process": proc.group("name") if proc else None,
            "pid": int(proc.group("pid")) if proc else None,
        })
    return sockets


def _port_from_addr(addr: str) -> int | None:
    """Pull the port out of an ``ss`` local-address column (IPv4/IPv6/``*``)."""
    if ":" not in addr:
        return None
    # The text after the final ':' is the port; the host part may carry an
    # interface suffix like ``%lo`` (``127.0.0.53%lo:53``), which we ignore.
    port = addr.rsplit(":", 1)[-1]
    return int(port) if port.isdigit() else None


# --- processes ------------------------------------------------------------
def parse_ps(text: str) -> list[Process]:
    """Parse ``ps -eo pid,user,%cpu,rss,comm --no-headers`` rows."""
    procs: list[Process] = []
    for line in text.splitlines():
        cols = line.split(maxsplit=4)
        if len(cols) < 5 or not cols[0].isdigit():
            continue
        pid, user, cpu, rss, comm = cols
        procs.append(Process(
            pid=int(pid),
            name=comm.strip(),
            user=user,
            cpu_percent=_as_float(cpu),
            rss_kb=int(rss) if rss.isdigit() else None,
        ))
    return procs


# --- systemd --------------------------------------------------------------
def parse_systemd_units(text: str) -> list[str]:
    """Parse ``systemctl list-units --no-legend --plain`` → unit names."""
    units: list[str] = []
    for line in text.splitlines():
        cols = line.split()
        if cols and cols[0].endswith(".service"):
            units.append(cols[0])
    return units


# --- containers -----------------------------------------------------------
def parse_docker_ps(text: str, runtime: str = "docker") -> list[Container]:
    """Parse ``docker ps -a --format '{{json .}}'`` (one JSON object per line).

    Defensive about Docker vs Podman field shapes: ``Names``/``Ports`` may be a
    string or a list, and label/mount strings are normalized to structured form.
    """
    containers: list[Container] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        labels = _parse_labels(obj.get("Labels"))
        containers.append(Container(
            id=str(obj.get("ID") or obj.get("Id") or "")[:12],
            name=_first(obj.get("Names") or obj.get("Name")),
            image=obj.get("Image"),
            state=_normalize_state(obj.get("State")),
            runtime=runtime,
            ports=_as_list(obj.get("Ports")),
            mounts=_as_list(obj.get("Mounts")),
            restart_policy=labels.get("restart") or None,
            compose_project=labels.get("com.docker.compose.project"),
            labels=labels,
        ))
    return containers


def _parse_labels(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        out: dict[str, str] = {}
        for part in raw.split(","):
            if "=" in part:
                k, _, v = part.partition("=")
                out[k.strip()] = v.strip()
        return out
    return {}


def _normalize_state(raw: object) -> str | None:
    if not raw:
        return None
    # Docker gives "running"; Podman sometimes "Up 2 hours" or "running".
    text = str(raw).strip()
    low = text.lower()
    if low.startswith("up"):
        return "running"
    if low.startswith("exited") or low.startswith("created"):
        return low.split()[0]
    return low


def _as_list(raw: object) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def _first(raw: object) -> str:
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    return str(raw or "")


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
