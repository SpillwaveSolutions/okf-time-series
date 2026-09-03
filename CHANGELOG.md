# Changelog

## 0.1.1 — 2026-09-03

- Index-free `walk` (`--flat`, `--kind`) over the filesystem. Directories are the index.
- `write-session --ensure-spine` (default on) creates missing Year→Month→Week→Day→Hour files and wires aggregates. Eager hours, as illustrated on #72 — not a vote on the threshold question.
- `rollup` attaches existing children to parent aggregates and does not rewrite summary prose.
- Command shims filled. `ots-walk` skill added.

## 0.1.0 — 2026-09-03

- Initial scaffold. Spec: okf-plugin#72.
- Node schemas for temporal.year/month/week/day/hour/session + telemetry/summary/saliency.
- Deterministic write helper (`scripts/ots_common.py`) validates period identifiers, aggregates, session slugs, close_reason, and AgentIdentity fields before disk.
