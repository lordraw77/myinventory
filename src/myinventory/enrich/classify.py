"""Tagging & role classification — the verdict step.

Runs last so it can weigh everything the earlier enrichers gathered: services
and their products, the OS guess, the SNMP ``sysDescr``, and the MAC's vendor.
It produces two things per host:

* a **role** (``hypervisor`` / ``nas`` / ``network`` / ``printer`` / …), assigned
  only when the host's current role is still ``unknown``/``physical`` so a role
  a backend already proved (VM, hypervisor) is never downgraded; and
* descriptive **tags** (``web-server``, ``database``, ``ssh``, ``vendor:cisco``…)
  that are always additive.

User-supplied :class:`~myinventory.config.ClassificationRule` objects run after
the built-in heuristics and, being explicit intent, may override the role.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from ..models import HostRole
from .base import Enricher, EnrichResult, register_enricher
from .oui import vendor_for_mac

if TYPE_CHECKING:
    from ..config import ClassificationRule, EnrichmentConfig
    from ..models import Host, Inventory

# Heuristics only assign a role when the current one is still weak, so a role a
# backend has *proven* (VM, hypervisor, container) is never downgraded.
_WEAK_ROLES = {HostRole.UNKNOWN, HostRole.PHYSICAL}

# service-name → tag for the always-additive descriptive tags.
_SERVICE_TAGS: dict[str, str] = {
    "http": "web-server",
    "https": "web-server",
    "http-alt": "web-server",
    "https-alt": "web-server",
    "mysql": "database",
    "postgresql": "database",
    "redis": "database",
    "mongodb": "database",
    "mssql": "database",
    "dns": "dns",
    "smtp": "mail",
    "imap": "mail",
    "imaps": "mail",
    "pop3": "mail",
    "ssh": "ssh",
    "rdp": "rdp",
    "smb": "file-sharing",
    "nfs": "file-sharing",
    "afp": "file-sharing",
}


def classify_host(
    host: Host,
    *,
    vendor: str | None = None,
    vendor_role: HostRole | None = None,
) -> tuple[HostRole | None, list[str]]:
    """Return ``(role_suggestion, tags)`` for ``host``.

    ``role_suggestion`` is ``None`` when no heuristic is confident; the caller
    decides whether to apply it. ``tags`` is always safe to union in.
    """
    names = {s.name for s in host.services if s.name}
    products = " ".join(
        " ".join(filter(None, (s.product, s.name))) for s in host.services
    ).lower()
    ports = {s.port for s in host.services}
    descr = str(host.extra.get("snmp_descr", "")).lower()
    blob = f"{products} {descr} {(host.os or '').lower()}"

    tags: list[str] = []
    for name in names:
        if name in _SERVICE_TAGS:
            tags.append(_SERVICE_TAGS[name])
    if host.containers:
        tags.append("container-host")
    if vendor:
        tags.append(f"vendor:{vendor.lower().replace(' ', '-')}")

    role = _suggest_role(host, names, ports, blob, vendor_role)
    if role is not None:
        tags.append(role.value)
    return role, _dedupe(tags)


def _suggest_role(
    host: Host,
    names: set[str],
    ports: set[int],
    blob: str,
    vendor_role: HostRole | None,
) -> HostRole | None:
    # Hypervisor: a proven hypervisor, or its management surface.
    if host.is_hypervisor or {"proxmox-ve", "vmware-esxi"} & names or {8006, 902} & ports:
        return HostRole.HYPERVISOR
    # NAS: vendor/product strings, or a file-sharing box that also serves a UI.
    if any(k in blob for k in ("synology", "qnap", "truenas", "unraid", "freenas")):
        return HostRole.NAS
    if {"smb", "nfs", "afp"} & names and {"http", "https", "http-alt"} & names:
        return HostRole.NAS
    # Printer.
    if {"jetdirect", "ipp", "printer"} & names or {9100, 515, 631} & ports:
        return HostRole.PRINTER
    # Network gear by SNMP/product strings.
    if any(k in blob for k in ("routeros", "mikrotik", "cisco ios", "edgeos", "vyos")):
        return HostRole.NETWORK
    # Otherwise fall back to whatever the MAC vendor implies (NAS/network/
    # printer/VM), which is weaker than any service-based verdict above.
    return vendor_role


def _rule_matches(host: Host, rule: ClassificationRule) -> bool:
    ports = {s.port for s in host.services}
    names = {s.name for s in host.services if s.name}
    if rule.ports and not (set(rule.ports) & ports):
        return False
    if rule.services and not (set(rule.services) & names):
        return False
    if rule.os_contains and rule.os_contains.lower() not in (host.os or "").lower():
        return False
    if rule.vendor_contains:
        vendor = str(host.extra.get("vendor", "")).lower()
        if rule.vendor_contains.lower() not in vendor:
            return False
    if rule.hostname_regex and not re.search(
        rule.hostname_regex, host.hostname or "", re.IGNORECASE
    ):
        return False
    # An all-empty rule matches nothing rather than everything.
    return any(
        (rule.ports, rule.services, rule.os_contains, rule.vendor_contains,
         rule.hostname_regex)
    )


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


@register_enricher("classify")
class ClassifierEnricher(Enricher):
    """Assign roles and descriptive tags from services, OS, vendor and rules."""

    def enrich(self, inventory: Inventory, config: EnrichmentConfig) -> EnrichResult:
        result = EnrichResult()
        for host in inventory.hosts.values():
            if self._classify(host, config):
                result.applied += 1
        return result

    def _classify(self, host: Host, config: EnrichmentConfig) -> bool:
        vendor, vendor_role = vendor_for_mac(host.mac)
        if vendor:
            host.extra.setdefault("vendor", vendor)

        before_role, before_tags = host.role, list(host.tags)

        role, tags = classify_host(host, vendor=vendor, vendor_role=vendor_role)
        if role is not None and host.role in _WEAK_ROLES:
            host.role = role
        host.tags = _dedupe([*host.tags, *tags])

        # User rules run last and may override even a proven role.
        for rule in config.rules:
            if _rule_matches(host, rule):
                if rule.role:
                    # An unknown role string keeps the tags but is ignored.
                    with contextlib.suppress(ValueError):
                        host.role = HostRole(rule.role)
                host.tags = _dedupe([*host.tags, *rule.tags])

        return host.role != before_role or host.tags != before_tags
