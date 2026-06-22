"""SNMP probe for network appliances (switches, APs, NAS, printers).

A great many devices that expose almost nothing useful over a port scan answer
SNMP happily. Polling the ``system`` group gives a device's own description,
name, location and ``sysObjectID`` — enough to name it, guess its OS and class
it as network gear / NAS / printer.

SNMP needs the ``snmp`` extra (``pip install 'myinventory[snmp]'``) and is opt-in
(``enrichment.snmp.enabled``). ``pysnmp`` is imported lazily inside
:func:`_snmp_query`; if the extra is missing the enricher records a single note
and does nothing. Tests monkeypatch :func:`_snmp_query` and never touch the wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..discovery._sweep import sweep
from ..models import Service
from .base import Enricher, EnrichResult, register_enricher

if TYPE_CHECKING:
    from ..config import EnrichmentConfig, SnmpConfig
    from ..models import Host, Inventory

# system-group OIDs we read.
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
_SYSTEM_OIDS = (
    OID_SYS_DESCR,
    OID_SYS_OBJECT_ID,
    OID_SYS_CONTACT,
    OID_SYS_NAME,
    OID_SYS_LOCATION,
)


class SnmpUnavailable(RuntimeError):
    """Raised when ``pysnmp`` is not installed."""


def parse_sys_descr(descr: str) -> dict[str, str]:
    """Pull coarse ``os``/``vendor`` hints out of a ``sysDescr`` string."""
    low = descr.lower()
    hints: dict[str, str] = {}
    for needle, vendor in (
        ("mikrotik", "MikroTik"),
        ("routeros", "MikroTik"),
        ("cisco", "Cisco"),
        ("ubiquiti", "Ubiquiti"),
        ("edgeos", "Ubiquiti"),
        ("unifi", "Ubiquiti"),
        ("synology", "Synology"),
        ("qnap", "QNAP"),
        ("juniper", "Juniper"),
        ("aruba", "Aruba"),
        ("hp ", "HP"),
        ("jetdirect", "HP"),
    ):
        if needle in low:
            hints["vendor"] = vendor
            break
    for needle, os_label in (
        ("windows", "Windows"),
        ("linux", "Linux"),
        ("routeros", "RouterOS"),
        ("cisco ios", "Cisco IOS"),
        ("junos", "Junos"),
    ):
        if needle in low:
            hints["os"] = os_label
            break
    return hints


# --- SNMP transport (module-level so tests can monkeypatch it) ------------
def _snmp_query(
    address: str,
    oids: tuple[str, ...],
    *,
    community: str,
    version: str,
    port: int,
    timeout: float,
    retries: int,
) -> dict[str, str] | None:
    """GET ``oids`` from ``address``; return ``{oid: value}`` or ``None``.

    ``None`` means the host did not answer. Raises :class:`SnmpUnavailable` when
    ``pysnmp`` is not installed so the caller can disable the whole pass once.
    """
    try:
        from pysnmp.hlapi import (  # type: ignore[import-untyped]
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
        )
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise SnmpUnavailable(str(exc)) from exc

    mp_model = 0 if version == "1" else 1
    engine = SnmpEngine()
    target = UdpTransportTarget((address, port), timeout=timeout, retries=retries)
    objects = [ObjectType(ObjectIdentity(o)) for o in oids]
    error_indication, error_status, _idx, var_binds = next(
        getCmd(engine, CommunityData(community, mpModel=mp_model), target,
               ContextData(), *objects)
    )
    if error_indication or error_status:
        return None
    out: dict[str, str] = {}
    for name, value in var_binds:
        out[str(name)] = str(value)
    return out


@register_enricher("snmp")
class SnmpEnricher(Enricher):
    """Poll the SNMP ``system`` group on every host and annotate the matches."""

    def enrich(self, inventory: Inventory, config: EnrichmentConfig) -> EnrichResult:
        result = EnrichResult()
        snmp = config.snmp
        if not snmp.enabled:
            return result

        targets = [
            h.primary_address for h in inventory.hosts.values() if h.primary_address
        ]
        if not targets:
            return result

        # ``sweep`` swallows per-probe exceptions, so a missing ``pysnmp`` would
        # silently look like "nothing answered". Capture it through a shared flag
        # and surface it once as a single, actionable note.
        unavailable: list[str] = []

        def probe(addr: str) -> dict[str, str] | None:
            try:
                return _snmp_query(
                    addr,
                    _SYSTEM_OIDS,
                    community=snmp.community,
                    version=snmp.version,
                    port=snmp.port,
                    timeout=snmp.timeout,
                    retries=snmp.retries,
                )
            except SnmpUnavailable as exc:
                if not unavailable:
                    unavailable.append(str(exc))
                return None

        replies, _ = sweep(targets, probe, workers=min(32, len(targets)))
        if unavailable:
            result.errors.append(
                f"enrich/snmp: pysnmp not installed ({unavailable[0]}); "
                f"install the 'snmp' extra to enable SNMP"
            )
            return result

        for host in inventory.hosts.values():
            data = replies.get(host.primary_address or "")
            if data and self._apply(host, data, snmp):
                result.applied += 1
        return result

    @staticmethod
    def _apply(host: Host, data: dict[str, str], snmp: SnmpConfig) -> bool:
        descr = data.get(OID_SYS_DESCR)
        name = data.get(OID_SYS_NAME)
        info = {
            "descr": descr,
            "name": name,
            "object_id": data.get(OID_SYS_OBJECT_ID),
            "contact": data.get(OID_SYS_CONTACT),
            "location": data.get(OID_SYS_LOCATION),
        }
        host.extra["snmp"] = {k: v for k, v in info.items() if v}
        if descr:
            host.extra["snmp_descr"] = descr
            host.extra.update(
                {f"snmp_{k}": v for k, v in parse_sys_descr(descr).items()}
            )
        if name and not host.hostname:
            host.hostname = name

        key = f"udp/{snmp.port}"
        if not any(s.key == key for s in host.services):
            host.add_service(
                Service(port=snmp.port, protocol="udp", name="snmp", source="snmp")
            )
        return True
