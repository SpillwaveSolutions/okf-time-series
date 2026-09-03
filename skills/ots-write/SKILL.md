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

`--ensure-spine` is on by default: missing Year→Hour files are created as `status: open` and aggregates are wired. Pass `--no-ensure-spine` to write a dangling session (the Hour threshold question on #72 is still open).

Never write frontmatter by hand. Children before parent aggregates. Do not invent summary prose in `rollup` — the model proposes, the script only links.
