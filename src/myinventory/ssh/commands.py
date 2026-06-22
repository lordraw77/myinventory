"""The read-only command set and the safety allow-list.

Deep inspection runs a fixed, auditable set of read-only commands. The allow-list
is the safety backstop required by the roadmap: every command the transport runs
is checked against it, so a future change can't silently introduce a mutating or
shell-injecting command.
"""

from __future__ import annotations

import shlex

# OS facts.
OS_RELEASE = "cat /etc/os-release"
UNAME = "uname -srm"
UPTIME = "uptime -p"
DETECT_VIRT = "systemd-detect-virt"

# Installed software, per package manager. The inspector picks by detected OS
# and falls back gracefully when a binary is absent.
DPKG = r"dpkg-query -W -f='${Package}\t${Version}\n'"
RPM = r"rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\n'"
SNAP = "snap list"
FLATPAK = "flatpak list --columns=application,version"

# Running state.
SS = "ss -H -tulpn"
PS = "ps -eo pid,user,%cpu,rss,comm --no-headers --sort=-%cpu"
SYSTEMCTL = (
    "systemctl list-units --type=service --state=running "
    "--no-legend --no-pager --plain"
)

# Container runtimes. ``{rt}`` is substituted with docker / podman. The Go
# template is single-quoted so the remote shell keeps ``{{json .}}`` (note the
# embedded space) as one argument instead of splitting it.
RUNTIME_VERSION = "{rt} --version"
RUNTIME_PS = "{rt} ps -a --no-trunc --format '{{{{json .}}}}'"

#: Binaries the inspector is permitted to invoke. The basename of every command
#: must be in here, and no command may contain a shell control operator.
ALLOWED_BINARIES = frozenset({
    "cat",
    "uname",
    "uptime",
    "systemd-detect-virt",
    "dpkg-query",
    "rpm",
    "snap",
    "flatpak",
    "ss",
    "ps",
    "systemctl",
    "docker",
    "podman",
})

# Characters that would chain, redirect or substitute a second command. Their
# presence means the string is more than one read-only invocation.
_FORBIDDEN = (";", "&", "|", "`", "$(", ">", "<", "\n")


class UnsafeCommandError(RuntimeError):
    """Raised when a command is not on the read-only allow-list."""


def assert_read_only(command: str) -> None:
    """Validate ``command`` against the allow-list, raising if it is unsafe."""
    for token in _FORBIDDEN:
        if token in command:
            raise UnsafeCommandError(
                f"refusing command with shell operator {token!r}: {command!r}"
            )
    try:
        parts = shlex.split(command)
    except ValueError as exc:  # unbalanced quoting, etc.
        raise UnsafeCommandError(f"un-parseable command: {command!r}") from exc
    if not parts:
        raise UnsafeCommandError("empty command")
    binary = parts[0].rsplit("/", 1)[-1]
    if binary not in ALLOWED_BINARIES:
        raise UnsafeCommandError(
            f"command {binary!r} is not on the read-only allow-list"
        )
