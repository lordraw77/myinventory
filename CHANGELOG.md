# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses semantic
versioning.

## [Unreleased]

Milestone 0 — Foundations (in progress, see [docs/roadmap.md](docs/roadmap.md)).

### Added
- Project scaffold, packaging (`pyproject.toml`), lint/type/test config.
- Full documentation set: architecture, roadmap, data model, configuration,
  discovery, output formats, usage, security, contributing, and ADRs 0001–0004.
- Core data model: `Host`, `Service`, `VirtualMachine`, `Network`, `Inventory`
  with stable IDs, field-level merge and JSON (de)serialization.
- Plugin registries + ABCs for discovery, service probes and virtualization.
- Reference backends: `tcp` host discovery, `banner` service probe, `proxmox`
  virtualization (collection logic wired, pending live test target).
- Pipeline orchestrator with discovery → service → virtualization → correlation
  stages and fail-soft error collection.
- JSON inventory repository with scan-over-scan merge.
- D2 renderer (network / subnet / hypervisor diagrams) and Markdown renderer
  (index + per-host pages).
- CLI: `scan`, `render`, `report`, `list`, `validate-config`.
- Test suite covering model round-trip, merge and both renderers.
