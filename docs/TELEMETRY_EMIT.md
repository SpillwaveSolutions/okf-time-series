# Telemetry emit view (read-time filter, not stored)

Phase-1 **summarization** contract. This is **not** a write format and is **not stored** in the bundle.

Source of truth: `sessions/<slug>.source.jsonl` (byte-for-byte vendor JSONL). See [PRD-TELEMETRY-PHASE1.md](PRD-TELEMETRY-PHASE1.md).

Haiku (and `summarize-hour`) project that snapshot through a host-switch filter:

- keep the user prompt
- keep the **final** assistant text in the turn
- skip `tool_result` (and tool-only assistant lines)

The in-memory view may look like the table below so a summarizer has a stable shape. **Do not append these objects into `.telemetry.md` as the capture.** `.telemetry.md` is optional / deferred in phase 1.

## Phase-1 view object (in memory only)

| Field | Required | Notes |
|-------|----------|-------|
| `v` | yes | start `1` |
| `ts` | yes | ISO-8601 UTC |
| `host` | yes | `claude-code` \| `grok-build` \| `codex` \| `deep-agents` |
| `session_id` | yes | matches `temporal.session` `id` |
| `actor` | yes | `SECOND_BRAIN_IDENTITY` |
| `turn` | yes | monotonic int in session |
| `role` | yes | `user` \| `assistant` |
| `text` | yes | prompt or final assistant text only |
| `model` | no | |

Implemented by `scripts/ots_filter.py`. No LLM in the filter. No tool-call fields in v1 (phase 2).

## Out of this contract

Stored vendor snapshot (the tailer), hourly tick, overnight pointer batch, Langfuse, tool-call capture (phase 2).
