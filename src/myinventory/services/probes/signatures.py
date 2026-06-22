"""Static service signatures used by the banner probe.

Two lookups:

* ``WELL_KNOWN_PORTS`` — port → logical service name, used when no banner is
  returned (common for binary protocols).
* :func:`identify` — match a connect-time banner against the signature table and
  return ``(name, product, version)``, extracting the version when the product
  advertises one (``OpenSSH_9.6p1`` → ``9.6p1``, ``nginx/1.25`` → ``1.25``).

The table is intentionally small and easy to extend. The optional ``nmap``
backend supersedes it when the ``nmap`` binary is available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WELL_KNOWN_PORTS: dict[int, str] = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "dns",
    67: "dhcp",
    80: "http",
    110: "pop3",
    111: "rpcbind",
    123: "ntp",
    135: "msrpc",
    139: "netbios",
    143: "imap",
    161: "snmp",
    389: "ldap",
    443: "https",
    445: "smb",
    515: "printer",
    548: "afp",
    631: "ipp",
    902: "vmware-esxi",
    993: "imaps",
    995: "pop3s",
    1433: "mssql",
    1883: "mqtt",
    2049: "nfs",
    3000: "http-alt",
    3306: "mysql",
    3389: "rdp",
    5000: "http-alt",
    5060: "sip",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8006: "proxmox-ve",
    8080: "http-alt",
    8123: "http-alt",
    8443: "https-alt",
    9000: "http-alt",
    9090: "cockpit",
    9100: "jetdirect",
    27017: "mongodb",
    32400: "plex",
}


@dataclass(frozen=True)
class Signature:
    """A banner fingerprint.

    ``needle`` is a lower-cased substring that flags the product's presence;
    ``version_re`` (matched against the original-case banner) optionally pulls
    the version out of capture group 1.
    """

    needle: str
    name: str
    product: str | None = None
    version_re: re.Pattern[str] | None = None


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Order matters: more specific products come before generic fallbacks.
SIGNATURES: tuple[Signature, ...] = (
    # --- SSH --------------------------------------------------------------
    Signature("openssh", "ssh", "OpenSSH", _re(r"OpenSSH[_/]([\w.]+)")),
    Signature("dropbear", "ssh", "Dropbear", _re(r"dropbear[_/]([\w.]+)")),
    Signature("ssh-", "ssh", None, None),
    # --- HTTP servers -----------------------------------------------------
    Signature("server: nginx", "http", "nginx", _re(r"nginx/([\w.]+)")),
    Signature("server: apache", "http", "Apache", _re(r"Apache/([\w.]+)")),
    Signature("server: microsoft-iis", "http", "IIS", _re(r"IIS/([\w.]+)")),
    Signature("server: lighttpd", "http", "lighttpd", _re(r"lighttpd/([\w.]+)")),
    Signature("server: caddy", "http", "Caddy", None),
    Signature("server: gunicorn", "http", "gunicorn", _re(r"gunicorn/([\w.]+)")),
    Signature("server: werkzeug", "http", "Werkzeug", _re(r"Werkzeug/([\w.]+)")),
    Signature("http/1.", "http", None, None),
    # --- mail -------------------------------------------------------------
    Signature("postfix", "smtp", "Postfix", None),
    Signature("exim", "smtp", "Exim", _re(r"Exim ([\w.]+)")),
    Signature("220 ", "smtp", None, None),
    Signature("dovecot", "imap", "Dovecot", None),
    Signature("* ok", "imap", None, None),
    Signature("+ok", "pop3", None, None),
    # --- FTP --------------------------------------------------------------
    Signature("vsftpd", "ftp", "vsftpd", _re(r"vsFTPd ([\w.]+)")),
    Signature("proftpd", "ftp", "ProFTPD", _re(r"ProFTPD ([\w.]+)")),
    Signature("filezilla", "ftp", "FileZilla", None),
    Signature("220", "ftp", None, None),
    # --- databases / caches ----------------------------------------------
    Signature("mariadb", "mysql", "MariaDB", _re(r"([\d.]+)-MariaDB")),
    Signature("mysql", "mysql", "MySQL", _re(r"([\d.]+)-")),
    Signature("redis_version", "redis", "Redis", _re(r"redis_version:([\w.]+)")),
    # --- misc -------------------------------------------------------------
    Signature("rfb 00", "vnc", "VNC", _re(r"RFB (\d{3}\.\d{3})")),
)


def identify(banner: str, port: int) -> tuple[str | None, str | None, str | None]:
    """Return ``(name, product, version)`` for ``banner`` seen on ``port``.

    Falls back to the well-known-port name when nothing matches.
    """
    low = banner.lower()
    for sig in SIGNATURES:
        if sig.needle in low:
            version: str | None = None
            if sig.version_re is not None:
                match = sig.version_re.search(banner)
                if match:
                    version = match.group(1)
            return sig.name, sig.product, version
    return WELL_KNOWN_PORTS.get(port), None, None


# Backwards-compatible alias for the previous (name, product) table shape.
BANNER_SIGNATURES = SIGNATURES
