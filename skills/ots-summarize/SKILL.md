---
name: ots-summarize
description: After tick-hour, read .source.jsonl, apply the host-switch filter, write summary and saliency. Edition A (host CLI) or B (API key). Does not touch the snapshot.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" summarize \
  --period 2026-08-21T14 \
  --author "$SECOND_BRAIN_IDENTITY" \
  --bundle "$SECOND_BRAIN_ROOT"
```

The model runs **inline** (Edition A or B from `okf/temporal/tailer.json`). No hidden queue. Scheduler is the user's cron — `ots print-cron` prints suggested lines.

Edition A (no API key) always passes the pinned cheapest model:

- Claude Code: `claude -p --model claude-haiku-4-5`
- Codex: `codex exec -m gpt-5.6-luna`
- Grok Build: `grok --model grok-4-fast -p`

Missing CLI or wrong model fails loudly. No silent fallback to Edition B.

Edition B: `ANTHROPIC_API_KEY` → `claude-haiku-4-5`; `OPENAI_API_KEY` → `gpt-5.6-luna`. Same prompt and files.

Tests / air-gapped:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" summarize \
  --period 2026-08-21T14 \
  --author "$SECOND_BRAIN_IDENTITY" \
  --bundle "$SECOND_BRAIN_ROOT" \
  --stub
```

`--model-cmd` is an explicit override, not Edition B.

Inspect (no model call):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" sessions list --period 2026-08-21T14 --bundle "$SECOND_BRAIN_ROOT"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" sessions show --id software_engineer__local__001 --bundle "$SECOND_BRAIN_ROOT"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots" summarize --status --period 2026-08-21T14 --bundle "$SECOND_BRAIN_ROOT"
```

Filter (not stored): user prompt + final assistant; skip `tool_result`. Never rewrite `.source.jsonl`. Overnight pointers stay out of scope.
