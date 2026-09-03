---
name: ots-write
description: Commit a temporal node. The model proposes body text; this script writes frontmatter.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" write-session \
  --id software_engineer__atlas__001 \
  --period 2026-08-21T14 \
  --agent-name atlas --agent-role software_engineer \
  --author "$SECOND_BRAIN_IDENTITY" --bundle "$SECOND_BRAIN_ROOT"
```

Hour nodes come from `tick-hour`, not from session writes. `--ensure-spine` is **off** by default. Pass it only for fixtures.

A session that crosses an hour boundary closes its segment and opens the next (`close-segment --period YYYY-MM-DDTHH`), so each segment belongs to exactly one Hour.

Never write frontmatter by hand. Children before parent aggregates. Do not invent summary prose in `rollup` — the model proposes, the script only links.
