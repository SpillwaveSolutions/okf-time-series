# Telemetry emit body (phase 1)

Body JSONL convention for `temporal.telemetry`. **Not** frontmatter.

Frontmatter stays [Telemetry.schema.json](Telemetry.schema.json): `type`, `title`, `session`, `author`, `timestamp`.

Raw telemetry is append-only and immutable. One JSON object per line inside a ` ```jsonl ` fence. No LLM in the tailer. No tool-call fields in v1.

## Phase-1 line object

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
| `source_path` | no | host JSONL path |
| `source_offset` | no | byte offset for idempotent re-tail |

Older samples may have used `t` / `kind` aliases. Locked names above win; this pack's samples use the locked fields.

## Fence

```jsonl
{"v":1,"ts":"2026-08-21T14:03:11Z","host":"claude-code","session_id":"software_engineer__atlas__001","actor":"grok-bot/northstar-console","turn":1,"role":"user","text":"scaffold the ingest write helper"}
```

Create the `.telemetry.md` file once (frontmatter + empty fence). After that **only append** lines inside the fence. Never rewrite earlier records.

## Out of this contract

Haiku hour-close summary, overnight pointer batch, Langfuse, tool-call capture (phase 2).
