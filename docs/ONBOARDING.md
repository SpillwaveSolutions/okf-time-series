# Onboarding — okf-time-series

Spec of record: https://github.com/SpillwaveSolutions/okf-plugin/issues/72

This pack is part of the Spillwave OKF family. Read [second-brain-core/docs/ONBOARDING.md](https://github.com/SpillwaveSolutions/second-brain-core/blob/main/docs/ONBOARDING.md) first.

Destination state: Grok Bots and local agents sharing one git-native second brain. Temporal memory, pointers, and remoting are the spine that makes capture plugins time-aware.

Public repo: https://github.com/SpillwaveSolutions/okf-time-series

Samples stay **Northstar / Lumenfield** fiction.

Ingest pipeline (each step is its own process):

`ots_tail_jsonl.py` (snapshot) → `tick-hour` → `summarize --period` → `rollup` → overnight pointers (separate)

`scripts/ots` is a thin dispatcher (`ots once`, `ots summarize`, `ots sessions list`, `ots print-cron`).

The tailer is read-only on the host JSONL and copies it to `sessions/<slug>.source.jsonl`. No vendor-neutral emit JSONL is stored. No LLM in the tailer. Summarization applies the host-switch filter at read time: [TELEMETRY_EMIT.md](TELEMETRY_EMIT.md). Three planes + snapshot rule: [PRD-TELEMETRY-PHASE1.md](PRD-TELEMETRY-PHASE1.md).
