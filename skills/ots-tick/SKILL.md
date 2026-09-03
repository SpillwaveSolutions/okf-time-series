---
name: ots-tick
description: Scheduled hourly tick. Writes an Hour node only when the window has closed sessions and no open ones. Sparse.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" tick-hour \
  --period 2026-08-21T14 \
  --author "$SECOND_BRAIN_IDENTITY" --bundle "$SECOND_BRAIN_ROOT"
```

- No sessions in the window → no node is written.
- Any session with `status: open` → skip and revisit after close. Do not write partial summaries.
- Long sessions leave un-finalized Hours behind them. That is intended.

Pass `--ensure-parents` to create missing Year→Day containers. Default is sparse.
