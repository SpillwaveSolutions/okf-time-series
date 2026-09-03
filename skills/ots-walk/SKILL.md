---
name: ots-walk
description: Walk Year → Month → Week → Day → Hour → Session using only the filesystem.
---

# ots-walk

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" walk --bundle "$SECOND_BRAIN_ROOT"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" walk --flat --kind session --bundle "$SECOND_BRAIN_ROOT"
```

Index-free. Directories are the index. Ticket/epic entry goes through okf-pointers, which is blocked on okf-plugin#73 §2.3.
