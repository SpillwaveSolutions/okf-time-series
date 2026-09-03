---
name: ots-prune
description: Drop telemetry files older than 90 days. Pruning is a git commit of the working tree.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" prune-telemetry \
  --days 90 --bundle "$SECOND_BRAIN_ROOT"
```

Default retention is 90 days (`OKF_TELEMETRY_RETENTION_DAYS`). Hubs, summaries, and saliency stay. `--dry-run` lists without deleting.
