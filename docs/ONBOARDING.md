# Onboarding — okf-time-series

Spec of record: https://github.com/SpillwaveSolutions/okf-plugin/issues/72

This pack is part of the Spillwave OKF family. Read [second-brain-core/docs/ONBOARDING.md](https://github.com/SpillwaveSolutions/second-brain-core/blob/main/docs/ONBOARDING.md) first.

Destination state: Grok Bots and local agents sharing one git-native second brain. Temporal memory, pointers, and remoting are the spine that makes capture plugins time-aware.

Public repo: https://github.com/SpillwaveSolutions/okf-time-series

Samples stay **Northstar / Lumenfield** fiction.

Ingest pipeline (each step is its own process):

`ots_tail_jsonl.py` (snapshot) → `tick-hour` → `summarize --period` → `rollup` → overnight pointers (separate)

`scripts/ots` is a thin dispatcher (`ots once`, `ots summarize`, `ots sessions list`, `ots print-cron`).

Capture is opt-in. `touch .okf-history` in the project, or `ots opt-in --jsonl <transcript>`. A bundle on disk is not opt-in. `status` / `check` print the absolute `.okf-history` candidates walked plus jsonl / session id when skipped.

After marketplace install, open the installed `plugin.json` and confirm **0.3.2** (catalog string ≠ git tag; 0.3.1 is the killed emit-schema write path). This pack is 0.3.3.

One-command gate: `python3 scripts/ots smoke`.

The tailer is read-only on the host JSONL and copies it to `sessions/<slug>.source.jsonl`. No vendor-neutral emit JSONL is stored. No LLM in the tailer. Summarization applies the host-switch filter at read time: [TELEMETRY_EMIT.md](TELEMETRY_EMIT.md). Three planes + snapshot rule: [PRD-TELEMETRY-PHASE1.md](PRD-TELEMETRY-PHASE1.md). Idle default 300s; dogfood may drop to 60 if follow stalls.
