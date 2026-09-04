---
name: ots-tick
description: Scheduled hourly tick. Writes Hour nodes from a directory listing. Revisits skipped Hours via the resume worklist.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" tick-hour \
  --period "$(date -u +%Y-%m-%dT%H)" \
  --author "$SECOND_BRAIN_IDENTITY" --bundle "$SECOND_BRAIN_ROOT"
```

That is the whole scheduler contract. One invocation per hour.

- Named period plus any earlier un-finalized Hour in `okf/temporal/.tick-resume.json`.
- The tick is a listing of that Hour's `sessions/` directory. Artifacts live in the Hour they belong to.
- Telemetry without summary → skip (open segment). Summary present → finalize. Empty directory → no node.
- Re-running over an already-finalized Hour is a no-op. Lost resume file rebuilds by scan of hour directories.

Pass `--ensure-parents` to create missing Year→Day containers. Default is sparse.
