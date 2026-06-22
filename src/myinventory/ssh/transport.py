"""SSH transport: run read-only commands on a Linux host via paramiko.

Imports ``paramiko`` lazily so the package stays importable without the ``[ssh]``
extra. Honors ``~/.ssh/config`` (hostname/user/port/identity/ProxyCommand), so
bastion/jump-host setups work through a standard ``ProxyJump``/``ProxyCommand``
entry. Host-key checking is strict by default.

Privileged commands are elevated with ``sudo -S`` fed the configured
``sudo_password`` (empty stdin for passwordless sudo). Every command is screened
by :func:`assert_read_only` before it runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .commands import assert_read_only

if TYPE_CHECKING:
    from ..config import LinuxSshTarget


@dataclass
class CommandResult:
    """Outcome of one remote command."""

    command: str
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class SshTransport:
    """A connected SSH session that runs allow-listed read-only commands."""

    def __init__(
        self,
        target: LinuxSshTarget,
        *,
        connect_timeout: float = 10.0,
        command_timeout: float = 20.0,
        strict_host_key: bool = True,
    ) -> None:
        self.target = target
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.strict_host_key = strict_host_key
        self._client: Any = None

    # --- lifecycle --------------------------------------------------------
    def connect(self) -> None:
        try:
            import paramiko  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on extra
            raise RuntimeError(
                "ssh inspection requires the 'ssh' extra: "
                "pip install 'myinventory[ssh]'"
            ) from exc

        client = paramiko.SSHClient()
        # ``load_system_host_keys`` only reads the *system* file
        # (/etc/ssh/ssh_known_hosts); the user's own ``~/.ssh/known_hosts`` —
        # where interactive ``ssh`` records hosts — must be loaded separately or
        # strict checking rejects hosts the user has already trusted.
        client.load_system_host_keys()
        user_known_hosts = Path("~/.ssh/known_hosts").expanduser()
        if user_known_hosts.exists():
            client.load_host_keys(str(user_known_hosts))
        policy = paramiko.RejectPolicy if self.strict_host_key else paramiko.AutoAddPolicy
        client.set_missing_host_key_policy(policy())

        client.connect(**self._connect_kwargs(paramiko))
        self._client = client

    def _connect_kwargs(self, paramiko: Any) -> dict:
        """Build paramiko ``connect`` kwargs, layering in ``~/.ssh/config``."""
        t = self.target
        kwargs: dict[str, Any] = {
            "hostname": t.host,
            "port": t.port,
            "username": t.username,
            "timeout": self.connect_timeout,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if t.password:
            kwargs["password"] = t.password
        if t.key_file:
            kwargs["key_filename"] = os.path.expanduser(t.key_file)

        # Layer in matching ~/.ssh/config options (host alias, identity, proxy).
        ssh_cfg = self._ssh_config(paramiko, t.host)
        if ssh_cfg:
            kwargs["hostname"] = ssh_cfg.get("hostname", t.host)
            if "user" in ssh_cfg and t.username == "root":
                kwargs["username"] = ssh_cfg["user"]
            if "port" in ssh_cfg:
                kwargs["port"] = int(ssh_cfg["port"])
            if "identityfile" in ssh_cfg and not t.key_file:
                kwargs["key_filename"] = ssh_cfg["identityfile"]
            if "proxycommand" in ssh_cfg:
                kwargs["sock"] = paramiko.ProxyCommand(ssh_cfg["proxycommand"])
        return kwargs

    @staticmethod
    def _ssh_config(paramiko: Any, host: str) -> dict:
        path = Path("~/.ssh/config").expanduser()
        if not path.exists():
            return {}
        cfg = paramiko.SSHConfig()
        cfg.parse(path.open())
        return cfg.lookup(host)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            self._client = None

    def __enter__(self) -> SshTransport:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- command execution ------------------------------------------------
    def run(self, command: str, *, sudo: bool = False) -> CommandResult:
        """Run an allow-listed command, optionally elevated with ``sudo -S``."""
        assert_read_only(command)
        if self._client is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("connect() must be called before run()")

        wrapped = self._with_sudo(command) if sudo else command
        stdin, stdout, stderr = self._client.exec_command(
            wrapped, timeout=self.command_timeout
        )
        if sudo:
            # Feed the sudo password (or an empty line for passwordless sudo).
            stdin.write((self.target.sudo_password or "") + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        return CommandResult(command=command, stdout=out, stderr=err,
                             exit_status=status)

    @staticmethod
    def _with_sudo(command: str) -> str:
        # ``-S`` reads the password from stdin; ``-p ''`` suppresses the prompt.
        return f"sudo -S -p '' {command}"
