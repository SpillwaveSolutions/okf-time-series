---
name: ots-tail
description: Copy a host JSONL transcript into an immutable sessions/<slug>.source.jsonl snapshot. No LLM.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_tail_jsonl.py" once \
  --jsonl /path/to/host-session.jsonl \
  --host claude-code \
  --role software_engineer --agent atlas --n 1 \
  --author "${SECOND_BRAIN_IDENTITY:-local/tailer}" \
  --bundle "$SECOND_BRAIN_ROOT"
```

Commands: `once` · `follow` · `start` · `stop` · `status` · `check` · `setup` · `opt-in` · `opt-out` · `smoke`

Install is not capture. Create a project marker or opt in a transcript **before** anything is written:

```bash
touch .okf-history
# or one-off:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" opt-in --jsonl /path/to/host-session.jsonl --bundle "$SECOND_BRAIN_ROOT"
```

No marker and no session opt-in → skip entirely (no `.source.jsonl`, hub, or cursor). Do not infer opt-in from an existing OKF bundle.

- `--follow` / `follow` is long-running. `once` copies if the host grew, then exits.
- Idle flush default is 300 seconds (dogfood may use `--idle 60` if follow stalls; do not change the default unless asked). Cursor (`path`, `pos` or `size`/`mtime`, `session_id`, `updated_at`) makes restart idempotent.
- `check` exits 1 on missing source, unset identity, a stale cursor, or `not_opted_in`. `status` and `check` print the absolute `.okf-history` candidates walked plus jsonl / session id when skipped.
- `setup` writes `okf/temporal/tailer.json` in the bundle. `--edition a` verifies the host CLI + pinned cheapest model (`claude-haiku-4-5` / `gpt-5.6-luna` / `grok-4-fast`); `--edition b` verifies the API key env. Sonnet / Sol / Terra / any non-pin fails closed. Never hard-code a private remote. Optional overlay: `~/.okf/ots-tail.json`.
- Session hub via `write-session --ensure-spine`. Same slug across hours; new segment on hour rollover.
- `ots smoke` (or `ots-tail smoke`): fixtures + `--stub`. No API key.

Pipeline: tail → `tick-hour` → `summarize-hour` → `rollup` → overnight pointers (separate).

Do not run Haiku or pointer batch from the tailer. Do not store a vendor-neutral emit JSONL. Snapshot rule: [docs/PRD-TELEMETRY-PHASE1.md](../../docs/PRD-TELEMETRY-PHASE1.md). Read-time filter: [docs/TELEMETRY_EMIT.md](../../docs/TELEMETRY_EMIT.md).
