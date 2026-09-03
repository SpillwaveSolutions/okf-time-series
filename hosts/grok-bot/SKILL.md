---
name: grok-bot-okf-time-series
description: Bind a Grok Bot agent to okf-time-series. Isolation, identity, deterministic writes.
---

# Grok Bot / okf-time-series

Read docs/ONBOARDING.md first, then follow docs/GROK_BOT.md.

1. Identity: `grok-bot/okf-time-series`
2. Open an isolation session before writes (second-brain-core `scripts/brain_session.py open`) unless the human already pointed `SECOND_BRAIN_ROOT` at a session worktree.
3. Write owned types only (temporal.*) via this pack's scripts + `--author`.
4. Close the session to PR. Report path + SHA.
5. Never document a private remote. Never write raw Markdown into the tree.
