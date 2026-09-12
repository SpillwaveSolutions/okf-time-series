# Phase-1 telemetry — snapshot-first

Fiction only (Northstar / Lumenfield). Spec of record: [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72).

0.3.1 stored a vendor-neutral `TELEMETRY_EMIT` JSONL fence as the write path. That conflicts with this PRD. **0.3.2** flips capture to an immutable vendor snapshot.

## Three planes

| Plane | Process | Writes | LLM |
|-------|---------|--------|-----|
| **Capture** | `ots_tail_jsonl.py` once/follow/start | `sessions/<slug>.source.jsonl` + session hub + cursor | No |
| **Tick** | `ots_common.py tick-hour` | Hour node (sparse; skips an open segment) | No |
| **Summarize** | `ots_common.py summarize-hour` | `.summary.md` / `.saliency.md` | Yes (hour-close Haiku, stubbable) |

Overnight pointer batch is a later plane. Out of scope here.

## Snapshot rule

- Source of truth in the bundle: `sessions/<slug>.source.jsonl` — a **byte-for-byte** copy of the host JSONL.
- Replace the snapshot only when host size/mtime **grew**. Never shrink.
- **No vendor-neutral stored schema.** Do not normalize Claude / Grok / Codex into a custom emit JSONL as the stored capture.
- Adapters choose which file to copy and session boundaries only.
- `.telemetry.md` is optional / deferred in phase 1.

## Session hub

The tailer calls `write-session --ensure-spine` (flag confirmed on for this path; still off by default for hand writes). Same session slug across hours. Hour rollover runs `close-segment` on the current hour and opens the next — never mints `__002`.

## Cursor

`okf/temporal/.ots-cursor.json` (or `--cursor`): `path`, `pos` or `size`/`mtime`, `session_id`, `updated_at`. Makes re-tail idempotent. `check` exits 1 when the cursor is stale (`pos`/`size` ahead of the host file, or `path` mismatch), the host source is missing, or identity is unset.

## Read-time filter

Inference stays at hour-close. Haiku (or `summarize-hour`) reads `.source.jsonl` and applies the host-switch filter — user prompt + final assistant; skip `tool_result`. That view is **not stored**. Contract: [TELEMETRY_EMIT.md](TELEMETRY_EMIT.md).

## Config

`ots-tail setup` writes `okf/temporal/tailer.json` in the **bundle**. Never hard-code a private remote. Bundle root is `SECOND_BRAIN_ROOT`.

Idle flush default is 300 seconds. No host hooks. No LLM in the tailer.
