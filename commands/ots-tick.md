---
description: Run the hourly tick that writes sparse Hour nodes
---

Run the `ots-tick` skill. No segments → no node. Open segment → skip. Closed segments finalize even if the parent session is still running. See skills/ots-tick/SKILL.md and [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72).
