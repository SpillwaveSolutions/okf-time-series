# Changelog

## 0.3.2 — 2026-09-12

- Snapshot-first capture: `sessions/<slug>.source.jsonl` is the immutable vendor JSONL copy. No stored `TELEMETRY_EMIT` write schema.
- `ots_tail_jsonl.py` commands: `once` / `follow` / `start` / `stop` / `status` / `check` / `setup`. Cursor is `path`, `pos` or `size`/`mtime`, `session_id`, `updated_at`. Replace snapshot only if size/mtime grew; never shrink. Idle flush default 300s.
- `write-session --ensure-spine` confirmed for the tailer hub. Same slug across hours; `close-segment` on rollover.
- `TELEMETRY_EMIT` moved to `docs/TELEMETRY_EMIT.md` as the **read-time** filter for summarization (user prompt + final assistant; skip `tool_result`). Not stored.
- `ots summarize --period` reads the snapshot, applies the filter, writes `.summary.md` / `.saliency.md`, and does not touch `.source.jsonl`. Edition A (pinned host CLI) or Edition B (verified API key). No silent fallback. Tests use explicit `--stub` / `--model-cmd`.
- Setup `--edition a` fails if the host CLI is missing or the model is not the pin; `--edition b` fails if the key env is unset.
- `ots sessions list|show` and `ots summarize --status` show source/summary/saliency presence and excerpts. `ots print-cron` prints suggested crontab lines (user scheduler; not an in-pack queue).
- Setup writes `okf/temporal/tailer.json` in the bundle (optional `~/.okf/ots-tail.json` overlay). No private remotes. Phase-1 PRD: `docs/PRD-TELEMETRY-PHASE1.md`. `.telemetry.md` omitted in phase 1.

## 0.3.1 — 2026-09-12

- Phase-1 telemetry emit body contract: `schemas/okf-temporal/TELEMETRY_EMIT.md` (`v`, `ts`, `host`, `session_id`, `actor`, `turn`, `role`, `text`). Frontmatter unchanged.
- Official tailer `scripts/ots_tail_jsonl.py`: read-only host JSONL, skip `tool_result` user lines, idle-flush prompt → final assistant, cursor file for restart-without-duplicate.
- Tailer calls `write-session --ensure-spine` once and `close-segment` on hour rollover (same session id). No LLM, no Haiku, no pointers.
- Sample telemetry updated to the locked fence fields. Older `t`/`kind` aliases are not used.

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
