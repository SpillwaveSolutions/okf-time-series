# Changelog

## 0.3.0 — 2026-09-03

- Hourly tick skips only an Hour containing an **open segment**, not an open session. Closed segments finalize on the normal tick. At most one un-finalized Hour per running session.
- Session hub `segments[]` is an array of triples. Each segment carries `hour` and `status` (`open|closed`). `summary` and `saliency` are omitted while open and required once closed.
- `tick-hour` scans every session hub for `segments[].hour` (index-free). Re-running over a finalized Hour is a no-op.
- A closed segment is not partial. "Do not write partial summaries" stands.

## 0.2.0 — 2026-09-03

- Hour nodes come from `tick-hour`, not from session writes. Sparse: empty window writes nothing. An Hour that still contains an open session is skipped.
- `write-session --ensure-spine` is **off** by default.
- Milestone segments are hour-aligned. `close-segment` closes the current hour's segment so each belongs to exactly one Hour.
- `prune-telemetry --days 90` (default). Pruning is a git commit of the working tree.
- Watchdog is global, default one hour. `--role` is rejected (phase two).

## 0.1.1 — 2026-09-03

- Index-free `walk` (`--flat`, `--kind`) over the filesystem. Directories are the index.
- `write-session --ensure-spine` (default on) creates missing Year→Month→Week→Day→Hour files and wires aggregates. Eager hours, as illustrated on #72 — not a vote on the threshold question.
- `rollup` attaches existing children to parent aggregates and does not rewrite summary prose.
- Command shims filled. `ots-walk` skill added.

## 0.1.0 — 2026-09-03

- Initial scaffold. Spec: okf-plugin#72.
- Node schemas for temporal.year/month/week/day/hour/session + telemetry/summary/saliency.
- Deterministic write helper (`scripts/ots_common.py`) validates period identifiers, aggregates, session slugs, close_reason, and AgentIdentity fields before disk.
