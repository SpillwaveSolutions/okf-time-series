# OKF Time Series

Chronological spine for agent memory. Session → Hour → Day → Week → Month → Year. Plain markdown with YAML frontmatter, stored in an OKF bundle, committed to Git. No database required to traverse it.

**Spec of record:** [okf-plugin#72](https://github.com/SpillwaveSolutions/okf-plugin/issues/72)

Companion: [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers) (#73) · [okf-remote](https://github.com/SpillwaveSolutions/okf-remote) (#74)

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
