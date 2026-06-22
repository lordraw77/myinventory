"""Static service signatures used by the banner probe.

Two lookups:

* ``WELL_KNOWN_PORTS`` — port → logical service name, used when no banner is
  returned (common for binary protocols).
* ``BANNER_SIGNATURES`` — substring → ``(name, product)``, matched against the
  first bytes a service emits on connect.

This table is intentionally small and easy to extend. Milestone 1 grows it and
adds version extraction; the optional ``nmap`` backend supersedes it when the
``nmap`` binary is available.
"""

from __future__ import annotations

from typing import Dict, Tuple

WELL_KNOWN_PORTS: Dict[int, str] = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "dns",
    80: "http",
    110: "pop3",
    143: "imap",
    389: "ldap",
    443: "https",
    445: "smb",
    902: "vmware-esxi",
    1433: "mssql",
    3306: "mysql",
    3389: "rdp",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8006: "proxmox-ve",
    8080: "http-alt",
    9090: "cockpit",
    27017: "mongodb",
}

# Lower-cased substring found in the banner -> (logical name, product).
BANNER_SIGNATURES: Dict[str, Tuple[str, str]] = {
    "ssh-": ("ssh", "OpenSSH"),
    "http/1.": ("http", ""),
    "server: nginx": ("http", "nginx"),
    "server: apache": ("http", "Apache"),
    "server: microsoft-iis": ("http", "IIS"),
    "220 ": ("smtp", ""),
    "+ok": ("pop3", ""),
    "* ok": ("imap", ""),
    "mysql": ("mysql", "MySQL"),
    "-redis": ("redis", "Redis"),
}
