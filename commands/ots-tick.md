---
description: Run the hourly tick that writes sparse Hour nodes and revisits skipped Hours
---

Run the `ots-tick` skill. Scheduler is one `tick-hour --period` per hour; earlier skipped Hours come from the resume worklist. See skills/ots-tick/SKILL.md and [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72).
