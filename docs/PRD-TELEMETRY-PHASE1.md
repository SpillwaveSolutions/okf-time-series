# Phase-1 telemetry — snapshot-first

Fiction only (Northstar / Lumenfield). Spec of record: [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72).

0.3.1 stored a vendor-neutral `TELEMETRY_EMIT` JSONL fence as the write path. That conflicts with this PRD. **0.3.2** flips capture to an immutable vendor snapshot.

## Three planes

| Plane | Process | Writes | LLM |
|-------|---------|--------|-----|
| **Capture** | `ots_tail_jsonl.py` once/follow/start | `sessions/<slug>.source.jsonl` + session hub + cursor | No |
| **Tick** | `ots_common.py tick-hour` | Hour node (sparse; skips an open segment) | No |
| **Summarize** | `ots summarize --period` | `.summary.md` / `.saliency.md` | Yes (Edition A host CLI or Edition B API; inline) |

Overnight pointer batch is a later plane. Out of scope here.

## Snapshot rule

- Source of truth in the bundle: `sessions/<slug>.source.jsonl` — a **byte-for-byte** copy of the host JSONL.
- Replace the snapshot only when host size/mtime **grew**. Never shrink.
- **No vendor-neutral stored schema.** Do not normalize Claude / Grok / Codex into a custom emit JSONL as the stored capture.
- Adapters choose which file to copy and session boundaries only.
- `.telemetry.md` is **deferred / omitted** in phase 1. Hub + `.source.jsonl` are required.

## Session hub

The tailer calls `write-session --ensure-spine` (flag confirmed on for this path; still off by default for hand writes). Same session slug across hours. Hour rollover runs `close-segment` on the current hour and opens the next — never mints `__002`.

## Cursor

`okf/temporal/.ots-cursor.json` (or `--cursor`): `path`, `pos` or `size`/`mtime`, `session_id`, `updated_at`. Makes re-tail idempotent. `check` exits 1 when the cursor is stale (`pos`/`size` ahead of the host file, or `path` mismatch), the host source is missing, or identity is unset.

## Read-time filter

Inference stays at hour-close. `ots summarize --period` reads `.source.jsonl` and applies the host-switch filter — user prompt + final assistant; skip `tool_result`. That view is **not stored**. Contract: [TELEMETRY_EMIT.md](TELEMETRY_EMIT.md).

`--follow` refreshes the snapshot on **idle + size/mtime growth** (never shrink). Not an every-second mirror.

## Two summarize editions

Capture and storage are identical. Only the backend differs. Setup fails loudly; there is **no silent fallback** from A to B.

**Edition A — host CLI (no API key).** Wizard pins the cheapest model. Never trust the host default.

| Host | Command |
|------|---------|
| Claude Code | `claude -p --model claude-haiku-4-5` |
| Codex | `codex exec -m gpt-5.6-luna` |
| Grok Build | `grok --model grok-4-fast -p` |

If the CLI is missing or the model is not the pin, setup and summarize fail.

**Edition B — API key.** Direct HTTP: `ANTHROPIC_API_KEY` → `claude-haiku-4-5`; `OPENAI_API_KEY` → `gpt-5.6-luna`. Wizard refuses without a verified key env + pinned model. Same prompt and output files as A.

`ots summarize` invokes the model **inline**. The scheduler is the user's cron (`ots print-cron` prints suggested lines). Not a hidden queue.

## Config

Canonical path: bundle **`okf/temporal/tailer.json`**. Optional machine overlay: `~/.okf/ots-tail.json` (or `OKF_OTS_MACHINE_CONFIG`). Never a private remote. Never `/.okf/ots-tail.toml`.

```json
{
  "identity": "local/tailer",
  "host": "claude-code",
  "source": "/home/you/.claude/projects/northstar/session.jsonl",
  "idle": 300,
  "edition": "a",
  "model": "claude-haiku-4-5"
}
```

Edition B adds `provider` and `api_key_env`. Dogfood slug: `software_engineer__local__001`.

Idle flush default is 300 seconds. No host hooks. No LLM in the tailer. `worked_during` is not in this PR.

## Opt-in is the capture gate

Install ≠ capture. Both checks run **before** any snapshot, hub, or cursor write.

1. **Project-level:** `.okf-history` in the project root (empty file or short JSON). Optionally list directories in `okf/temporal/tailer.json` → `opt_in_dirs`. When the tailer is pointed at that project (`--project` / `OKF_PROJECT_ROOT` / cwd), new transcripts are picked up.
2. **Session-level:** `ots-tail opt-in --jsonl <transcript>` (and `opt-out`) for one-off or after-the-fact capture.

No marker and no session opt-in → **skip entirely**. Nothing written. Do **not** infer opt-in from “this directory already has an OKF / second-brain bundle.”

`ots-tail check` / `status` report `opted_in` and `skipped: not_opted_in`. Wizard documents `touch .okf-history` and `ots-tail opt-in`. Dogfood one project first; add dirs as trust grows.
