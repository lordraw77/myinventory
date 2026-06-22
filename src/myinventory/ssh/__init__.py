"""Agentless Linux deep inspection over SSH (roadmap M3).

A short-lived SSH session runs a fixed set of read-only commands and assembles a
software/process/container inventory for a host. Nothing is installed on the
target. Public surface:

* :class:`~myinventory.ssh.transport.SshTransport` — the paramiko connection.
* :class:`~myinventory.ssh.inspector.LinuxInspector` — turns command output into
  an enriched :class:`~myinventory.models.Host`.
* :func:`~myinventory.ssh.commands.assert_read_only` — the safety allow-list.
"""

from .commands import UnsafeCommandError, assert_read_only
from .inspector import LinuxInspector
from .transport import CommandResult, SshTransport

__all__ = [
    "SshTransport",
    "CommandResult",
    "LinuxInspector",
    "assert_read_only",
    "UnsafeCommandError",
]
