---
name: ots-watchdog
description: Close sessions open longer than the global watchdog (default one hour). Per-role is phase two.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py" watchdog \
  --author "$SECOND_BRAIN_IDENTITY" --bundle "$SECOND_BRAIN_ROOT"
```

`WATCHDOG_SECONDS` is global, default 3600. `--role` is rejected: per-role configuration is phase two — leave the hook, do not build it. Override with `--seconds` or `OKF_WATCHDOG_SECONDS`.
