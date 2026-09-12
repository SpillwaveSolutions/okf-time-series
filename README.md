# OKF Time Series

Chronological spine for agent memory. Session → Hour → Day → Week → Month → Year. Plain markdown with YAML frontmatter, stored in an OKF bundle, committed to Git. No database required to traverse it.

**Spec of record:** [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72)

Companion: [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers) (#73) · [okf-remote](https://github.com/SpillwaveSolutions/okf-remote) (#74)

**Installed version.** Marketplace catalog strings are not git tags. Marketplace 0.4.13 already pins OTS **0.3.2** / pointers 0.2.0. After install, open the installed `plugin.json` and confirm the version field is **0.3.2** (this pack is **0.3.3**). **0.3.1** is the killed emit-schema write path — do not dogfood it.

## Nouns this plugin may write

`temporal.year` · `temporal.month` · `temporal.week` · `temporal.day` · `temporal.hour` · `temporal.session` · `temporal.telemetry` · `temporal.summary` · `temporal.saliency`

Session `agent` resolves to existing `AgentIdentity` (second-brain-core). This plugin does not define a new identity type.

## Deterministic write boundary

The model proposes. Schema-enforced scripts commit:

```bash
python3 scripts/ots_common.py write-session \
  --id software_engineer__atlas__001 \
  --period 2026-08-21T14 \
  --agent-name atlas --agent-role software_engineer \
  --author "grok-bot/northstar-console" \
  --bundle "$SECOND_BRAIN_ROOT"

python3 scripts/ots_common.py tick-hour \
  --period 2026-08-21T14 \
  --author "grok-bot/northstar-console" \
  --bundle "$SECOND_BRAIN_ROOT"
```

Hour nodes come from the scheduled tick, not from session writes. No segments in the window means no Hour node — the hierarchy stays sparse. The tick skips only an Hour that still contains an **open segment**. Closed segments from a long session finalize on schedule. At most one Hour is un-finalized per running session.

Host transcripts enter through the official tailer (no LLM) **only after opt-in**. Install is not capture: `touch .okf-history` in the project root, or `ots opt-in --jsonl …`. The stored capture is a **byte-for-byte** `sessions/<slug>.source.jsonl` snapshot — not a vendor-neutral emit fence:

```bash
python3 scripts/ots_tail_jsonl.py once \
  --jsonl tests/fixtures/host-session.jsonl \
  --host claude-code \
  --role software_engineer --agent atlas --n 1 \
  --author "$SECOND_BRAIN_IDENTITY" \
  --bundle "$SECOND_BRAIN_ROOT"
```

`ots-tail` also has `start` / `stop` / `status` / `check` / `setup` / `smoke` (`setup` writes `okf/temporal/tailer.json`; never a private remote). `status` and `check` print the `.okf-history` paths walked when `skipped: not_opted_in`. `check` exits 1 if not opted in. One-command gate: `python3 scripts/ots smoke` (fixtures + `--stub`; no API key). Pipeline: tail → `tick-hour` → `summarize --period` → `rollup` → overnight pointers (separate; not in this pack). Summarize Edition A (host CLI + pinned cheapest model: `claude-haiku-4-5` / `gpt-5.6-luna` / `grok-4-fast`) or Edition B (API key). Setup fails closed on Sonnet / Sol / Terra / any non-pin. Inspect with `ots sessions list` / `show`. Cron helper: `ots print-cron`. Idle flush default is 300s (dogfood may use `--idle 60` if follow stalls). Phase-1 snapshot rule: [docs/PRD-TELEMETRY-PHASE1.md](docs/PRD-TELEMETRY-PHASE1.md). Emit table is a **read-time filter**, not stored: [docs/TELEMETRY_EMIT.md](docs/TELEMETRY_EMIT.md).

Milestone segments are hour-aligned. Telemetry retention defaults to 90 days. The watchdog is global, default one hour.

Never invent TypedEdge `rel` values — that vocabulary is owned by second-brain-core. Never invent Pointers `link_type` values — that taxonomy is owned by okf-pointers. This plugin writes neither. Never write types owned by another plugin. Never hard-code a private remote.

## Multi-host

| Host | How to load |
|------|-------------|
| Claude Code | marketplace + plugin install |
| Grok Build | zero-config Claude plugin |
| Codex | Agent Skills / `.codex-plugin` |
| Agent Plugins clients | root `plugin.json` + `skills/` |
| Grok Bot | [docs/GROK_BOT.md](docs/GROK_BOT.md) |
| Cursor | [docs/CURSOR.md](docs/CURSOR.md) |
| LangChain Deep Agents | [docs/LANG_CHAIN_DEEP_AGENTS.md](docs/LANG_CHAIN_DEEP_AGENTS.md) |

## Related plugins

- [second-brain-core](https://github.com/SpillwaveSolutions/second-brain-core)
- [okf-plugin](https://github.com/SpillwaveSolutions/okf-plugin)
- [okf-agent-graph](https://github.com/SpillwaveSolutions/okf-agent-graph)
- [wiki_ticket_sdd](https://github.com/SpillwaveSolutions/wiki_ticket_sdd)
- [project-knowledge-capture](https://github.com/SpillwaveSolutions/project-knowledge-capture)
- [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers)

## License

MIT. Copyright 2026 Rick Hightower / contributors.
