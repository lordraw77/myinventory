# ADR 0003 — D2 + Markdown as output formats

**Status:** Accepted

## Context

The whole point of the tool is human-consumable output: a picture of the network
and browsable documentation. Diagram options include Graphviz/DOT, Mermaid,
PlantUML and D2; doc options include HTML, Markdown and wiki-specific formats.

## Decision

Generate **D2** for diagrams and **Markdown** for documentation. Both are
emitted as text by pure renderers; image rendering (D2 → SVG/PNG) is left to the
`d2` CLI.

## Consequences

**Positive**

- Both formats are **plain text → diffable** in git, so re-scans produce
  reviewable changes, not opaque binaries.
- D2 has first-class **containers** (subnet boxes, hypervisor-with-nested-VMs),
  great auto-layout, and a clean syntax.
- Markdown renders everywhere (GitHub, wikis, MkDocs/Hugo) with zero lock-in.
- Renderers are pure functions of the model → trivially unit-testable.

**Negative**

- D2 → image needs the external `d2` binary (not pip-installable). Acceptable:
  the `.d2` source is the committed artifact; rendering is optional.
- Markdown is less rich than a bespoke web UI. A web/HTML view is a roadmap item
  (M5), layered on the same model — additive, not a rewrite. Mermaid/Graphviz
  renderers can be added behind the same renderer interface if needed.
