# Grok Bot binding — okf-time-series

Identity: `grok-bot/okf-time-series`

Owned types: temporal.year/month/week/day/hour/session + telemetry/summary/saliency

Write path: pack scripts + `--author`. The model proposes prose; scripts commit frontmatter.

Isolation: second-brain-core worktree + PR. Point `SECOND_BRAIN_ROOT` at the session bundle.

Never hard-code a private remote. Never invent `rel` values. Never write types owned by another plugin.
