# Changelog

## 0.3.3 — 2026-09-12

Dogfood gate only. No pointer batch, no Deep Agents, no Langfuse, no `worked_during`, no `.telemetry.md` revive.

- **Installed pin.** Marketplace 0.4.13 already pins OTS **0.3.2** / pointers 0.2.0. Catalog string ≠ git tag. After install, open the installed `plugin.json` and confirm the version field is **0.3.2** (this pack is **0.3.3** on top of that pin). **0.3.1** is the killed emit-schema write path — do not dogfood it.
- Fiction sample matches Phase-1: deleted `.telemetry.md`; hour 15 is the same slug `software_engineer__atlas__001` with a second segment (hub stays in hour 14). Sample must not teach `__002` for hour rollover. Pattern is `.source.jsonl` + hub + summary/saliency.
- `status` and `check` print the absolute `.okf-history` candidates walked plus `jsonl` / `session_id` when `skipped: not_opted_in`. `check` exits 1 if not opted in.
- `ots smoke` (also `ots-tail smoke`): `check && once && tick-hour && summarize --period … --stub && check`. Without `.okf-history` → exit 1 with those paths. With opt-in: snapshot hash unchanged after summarize; hub slug unchanged across a fake hour rollover. Fixtures + `--stub`; no API key.
- Setup fail-closed on Sonnet / Sol / Terra / any non-pin model. Never write the session default. Edition A pins `claude-haiku-4-5` (Claude), `gpt-5.6-luna` (Codex), `grok-4-fast` (Grok).
- Idle flush default stays **300** seconds. Dogfood may pass `--idle 60` if follow stalls; do not change the default unless asked.

## 0.3.2 — 2026-09-12

- Snapshot-first capture: `sessions/<slug>.source.jsonl` is the immutable vendor JSONL copy. No stored `TELEMETRY_EMIT` write schema.
- `ots_tail_jsonl.py` commands: `once` / `follow` / `start` / `stop` / `status` / `check` / `setup`. Cursor is `path`, `pos` or `size`/`mtime`, `session_id`, `updated_at`. Replace snapshot only if size/mtime grew; never shrink. Idle flush default 300s.
- `write-session --ensure-spine` confirmed for the tailer hub. Same slug across hours; `close-segment` on rollover.
- `TELEMETRY_EMIT` moved to `docs/TELEMETRY_EMIT.md` as the **read-time** filter for summarization (user prompt + final assistant; skip `tool_result`). Not stored.
- `ots summarize --period` reads the snapshot, applies the filter, writes `.summary.md` / `.saliency.md`, and does not touch `.source.jsonl`. Edition A (pinned host CLI) or Edition B (verified API key). No silent fallback. Tests use explicit `--stub` / `--model-cmd`.
- Setup `--edition a` fails if the host CLI is missing or the model is not the pin; `--edition b` fails if the key env is unset.
- `ots sessions list|show` and `ots summarize --status` show source/summary/saliency presence and excerpts. `ots print-cron` prints suggested crontab lines (user scheduler; not an in-pack queue).
- Setup writes `okf/temporal/tailer.json` in the bundle (optional `~/.okf/ots-tail.json` overlay). No private remotes. Phase-1 PRD: `docs/PRD-TELEMETRY-PHASE1.md`. `.telemetry.md` omitted in phase 1.
- Capture is opt-in. `.okf-history` (project) or `ots-tail opt-in` (session). No marker → skip entirely (no snapshot/hub/cursor). A bundle on disk is not opt-in. `check`/`status` report skipped vs opted-in.

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
