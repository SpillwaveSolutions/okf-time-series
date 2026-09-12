# Onboarding — okf-time-series

Spec of record: https://github.com/SpillwaveSolutions/okf-plugin/issues/72

This pack is part of the Spillwave OKF family. Read [second-brain-core/docs/ONBOARDING.md](https://github.com/SpillwaveSolutions/second-brain-core/blob/main/docs/ONBOARDING.md) first.

Destination state: Grok Bots and local agents sharing one git-native second brain. Temporal memory, pointers, and remoting are the spine that makes capture plugins time-aware.

Public repo: https://github.com/SpillwaveSolutions/okf-time-series

Samples stay **Northstar / Lumenfield** fiction.

Ingest pipeline (each step is its own process):

`ots_tail_jsonl.py` → `tick-hour` → `rollup` → Haiku summary (separate) → overnight pointers (separate)

The tailer is read-only on the host JSONL and writes append-only `temporal.telemetry` under `path_for`. Body contract: [schemas/okf-temporal/TELEMETRY_EMIT.md](../schemas/okf-temporal/TELEMETRY_EMIT.md). No LLM in the tailer.
