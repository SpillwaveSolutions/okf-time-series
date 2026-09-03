---
name: ots-validate
description: Validate temporal nodes: type, period, aggregates, session identity.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" validate --bundle "$SECOND_BRAIN_ROOT"
```

Fail on unowned types, dangling aggregates, invalid close_reason/status, or a session whose agent block is missing.
