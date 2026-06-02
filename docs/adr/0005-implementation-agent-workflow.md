# 5. Implementation agent & review workflow

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The rewrite is delivered in vertical, test-gated phases (see `PLAN.md`). We must decide how to use AI agents during implementation: a standing team of specialized sub-agents (e.g. separate implement / test / review agents running together) versus a single driver agent per phase. Sub-agents start with cold context and must re-derive project understanding from the docs, which is expensive and loses the nuance captured during planning. The phases are small, coherent vertical slices where tests are part of the implementation cycle, not a separate workstream.

## Decision

**One primary "driver" agent per phase, with context cleared between phases. Sub-agents are spawned surgically on-demand, not as a standing team.**

Per-phase loop:
1. Fresh session opens with: "Read `PRD.md`, `PLAN.md`, `research.md`, `initial-codebase-analysis.md`, then execute Phase N."
2. Plan the slice (track sub-steps with the task tools).
3. Implement **and** write tests together.
4. Run unit / integration / Playwright — the phase gate must pass.
5. Independent review at the gate via the `/code-review` skill (`/code-review ultra` for deep cloud multi-agent review); the operator triggers it.
6. Commit on a `phase-N-<name>` branch → open PR via `gh` → merge.
7. Clear context → next phase.

Sub-agents are used **only** where isolation adds clear value:
- **End-of-phase code review** — independence is the whole point (or use `/code-review`).
- **Exploration** of unfamiliar areas — keeps the driver's context lean.
- **Long-running background tasks** (e.g. a long test/backtest run).

We do **not** run parallel role-specialized agents (impl/test/review) within a single phase.

**Model selection is manual.** The agent does not (and cannot) auto-switch its own model or auto-clear its own context in the driver session. At each phase start the operator runs `/clear` then `/model <opus|sonnet>` per the recommended-model table in `PLAN.md` §7.2 (Opus 4.8 for correctness-critical phases, Sonnet 4.6 for mechanical ones). Live progress is tracked in `PROGRESS.md`.

## Consequences

- Independence benefit is captured exactly where it matters (review) without paying the cold-start context tax multiple times per phase.
- Context stays lean: cleared at each phase seam, which is the natural boundary already defined by the plan.
- Tests are written by the implementer as part of the slice (no handoff overhead).
- Requires `gh` authenticated for issues/PRs; defects found mid-phase become GitHub issues referenced in the fixing commit/PR.
