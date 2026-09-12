---
name: ots-summarize
description: After tick-hour, read .source.jsonl, apply the host-switch filter, write summary and saliency. Does not touch the snapshot.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" summarize-hour \
  --period 2026-08-21T14 \
  --host claude-code \
  --author "$SECOND_BRAIN_IDENTITY" \
  --bundle "$SECOND_BRAIN_ROOT"
```

Haiku (or any model) is invoked here, not in the tailer. Tests and air-gapped runs stub the call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" summarize-hour \
  --period 2026-08-21T14 \
  --author "$SECOND_BRAIN_IDENTITY" \
  --bundle "$SECOND_BRAIN_ROOT" \
  --model-cmd 'python3 -c "import sys,json; json.load(sys.stdin); print(json.dumps({\"summary\":\"(stub)\",\"saliency\":\"- (stub)\"}))"'
```

`OKF_SUMMARIZE_CMD` is the env equivalent. If neither is set, a deterministic stub runs — no API key required.

Filter (not stored): user prompt + final assistant; skip `tool_result`. Contract: [docs/TELEMETRY_EMIT.md](../../docs/TELEMETRY_EMIT.md). Never rewrite `.source.jsonl`. Overnight pointers stay out of scope.
