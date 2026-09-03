# CLAUDE.md — okf-time-series

You are operating the **OKF Time Series** plugin. Spec of record: https://github.com/SpillwaveSolutions/okf-plugin/issues/72

## When to use

Chronological agent memory. Session → Hour → Day → Week → Month → Year. Read `docs/ONBOARDING.md` first.

## Write path

1. Identify the noun (`temporal.year|month|week|day|hour|session` plus telemetry/summary/saliency).
2. Check `schemas/okf-temporal/` for required fields.
3. Call `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ots_common.py write-session|write-aggregate|write-artifact ...`
4. The model proposes summary and saliency prose. This script commits frontmatter.
5. Session `agent` resolves to existing `AgentIdentity`. Do not define a new identity type.

## Do not

- Invent `rel` values.
- Write types owned by another plugin.
- Hard-code a private remote. Use `SECOND_BRAIN_ROOT`.
- Silently answer open questions on #72.
- Depend on BM25, vector, or graph indexes for correctness.
