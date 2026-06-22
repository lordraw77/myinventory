"""A small MAC OUI → vendor (and role hint) table.

Like the banner ``signatures`` table this is intentionally compact and easy to
extend — it covers the vendors a homelab actually meets (virtualization,
network gear, NAS, single-board computers, printers) rather than the full IEEE
registry. :func:`vendor_for_mac` returns the vendor name and, when the vendor
strongly implies a device class, a :class:`~myinventory.models.HostRole` hint
that the classifier can use.
"""

from __future__ import annotations

from ..models import HostRole

# Keyed by the 24-bit OUI as ``aa:bb:cc`` (lower-case). ``role`` is a hint, not
# a verdict — the classifier weighs it against services and SNMP data.
_OUI: dict[str, tuple[str, HostRole | None]] = {
    # --- virtualization (locally-administered / vendor ranges) -----------
    "00:0c:29": ("VMware", HostRole.VM),
    "00:50:56": ("VMware", HostRole.VM),
    "00:05:69": ("VMware", HostRole.VM),
    "00:1c:14": ("VMware", HostRole.VM),
    "08:00:27": ("VirtualBox", HostRole.VM),
    "52:54:00": ("QEMU/KVM", HostRole.VM),
    "00:16:3e": ("Xen", HostRole.VM),
    "00:15:5d": ("Hyper-V", HostRole.VM),
    # --- network gear ----------------------------------------------------
    "00:0c:42": ("MikroTik", HostRole.NETWORK),
    "dc:2c:6e": ("MikroTik", HostRole.NETWORK),
    "48:8f:5a": ("MikroTik", HostRole.NETWORK),
    "24:a4:3c": ("Ubiquiti", HostRole.NETWORK),
    "fc:ec:da": ("Ubiquiti", HostRole.NETWORK),
    "78:8a:20": ("Ubiquiti", HostRole.NETWORK),
    "b4:fb:e4": ("Ubiquiti", HostRole.NETWORK),
    "00:1a:a0": ("Cisco", HostRole.NETWORK),
    "00:1b:0c": ("Cisco", HostRole.NETWORK),
    "00:25:45": ("Cisco", HostRole.NETWORK),
    "00:14:6c": ("Netgear", HostRole.NETWORK),
    "a0:40:a0": ("Netgear", HostRole.NETWORK),
    "14:cc:20": ("TP-Link", HostRole.NETWORK),
    "50:c7:bf": ("TP-Link", HostRole.NETWORK),
    "00:0b:86": ("Aruba", HostRole.NETWORK),
    # --- NAS -------------------------------------------------------------
    "00:11:32": ("Synology", HostRole.NAS),
    "00:08:9b": ("QNAP", HostRole.NAS),
    "24:5e:be": ("QNAP", HostRole.NAS),
    # --- single-board computers (usually plain Linux hosts) --------------
    "b8:27:eb": ("Raspberry Pi", None),
    "dc:a6:32": ("Raspberry Pi", None),
    "e4:5f:01": ("Raspberry Pi", None),
    # --- printers --------------------------------------------------------
    "00:01:e6": ("HP", HostRole.PRINTER),
    "00:21:5a": ("HP", HostRole.PRINTER),
    "00:00:48": ("Epson", HostRole.PRINTER),
    "08:00:37": ("Fuji Xerox", HostRole.PRINTER),
    "00:00:85": ("Canon", HostRole.PRINTER),
}


def _normalize(mac: str) -> str:
    return mac.lower().replace("-", ":").strip()


def vendor_for_mac(mac: str | None) -> tuple[str | None, HostRole | None]:
    """Return ``(vendor, role_hint)`` for ``mac`` (``(None, None)`` if unknown)."""
    if not mac:
        return None, None
    parts = _normalize(mac).split(":")
    if len(parts) < 3:
        return None, None
    oui = ":".join(parts[:3])
    return _OUI.get(oui, (None, None))
