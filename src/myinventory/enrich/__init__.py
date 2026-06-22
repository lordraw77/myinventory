"""Enrichment plugins: turn discovered hosts into *identified* hosts.

The Milestone-4 passes — SNMP, hostname (reverse-DNS/DHCP), OS fingerprinting and
classification — run after discovery/virtualization/correlation and annotate the
inventory in place. ``ENRICHMENT_ORDER`` is the order the orchestrator applies
them so each pass can build on the previous one's output.
"""

# Importing the concrete enrichers registers them as a side effect.
from . import classify, dns, fingerprint, snmp  # noqa: F401
from .base import Enricher, EnrichResult, available, get_enricher, register_enricher

#: Fixed application order: SNMP first (richest facts), then names, then the OS
#: guess, then classification (which consumes everything above).
ENRICHMENT_ORDER = ("snmp", "hostname", "fingerprint", "classify")

__all__ = [
    "Enricher",
    "EnrichResult",
    "register_enricher",
    "get_enricher",
    "available",
    "ENRICHMENT_ORDER",
]
