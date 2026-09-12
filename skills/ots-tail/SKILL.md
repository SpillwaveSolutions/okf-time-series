---
name: ots-tail
description: Drain a host JSONL transcript into append-only temporal.telemetry. No LLM.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_tail_jsonl.py" --once \
  --jsonl /path/to/host-session.jsonl \
  --host claude-code \
  --role software_engineer --agent atlas --n 1 \
  --author "${SECOND_BRAIN_IDENTITY:-local/tailer}" \
  --bundle "$SECOND_BRAIN_ROOT" \
  --cursor /tmp/host-session.ots-cursor.json
```

`--follow` is the default long-running mode. `--once` drains to EOF and exits.

Pipeline (this process is only the first step):

tail → `tick-hour` → `rollup` → Haiku summary (separate) → overnight pointers (separate)

Do not run Haiku or pointer batch from the tailer. Body contract: `schemas/okf-temporal/TELEMETRY_EMIT.md`.
