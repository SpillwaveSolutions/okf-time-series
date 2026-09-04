---
name: ots-tick
description: Scheduled hourly tick. Writes an Hour node only when the window has closed segments and no open ones. Sparse.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" tick-hour \
  --period 2026-08-21T14 \
  --author "$SECOND_BRAIN_IDENTITY" --bundle "$SECOND_BRAIN_ROOT"
```

- No segments in the window → no node is written.
- An open segment in that Hour → skip. Do not write partial summaries. A closed segment is not partial.
- Earlier Hours a long session already crossed hold only closed segments and finalize on their normal tick. At most one Hour per running session is un-finalized.
- Re-running over an already-finalized Hour is a no-op.

Pass `--ensure-parents` to create missing Year→Day containers. Default is sparse.
