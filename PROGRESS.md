# statsArbBot — Progress Tracker

**Living status file. Read first at the start of every session.** Update at each phase boundary.
Companion docs: `PRD.md` (what), `PLAN.md` (how + per-phase model in §7.2), `docs/adr/` (decisions).

- **Status legend:** ⬜ not started · 🟡 in progress · ✅ done (gate passed + merged) · 🔴 blocked
- **Gate = phase complete only when:** unit + integration + (UI) Playwright tests pass → `/code-review ultra` → PR merged.

---

## Current Position

- **Phase in progress:** _none — planning complete, implementation not yet started (awaiting go-ahead)_
- **Next action:** Phase 0 — `/clear`, `/model sonnet`, then "Read PRD.md, PLAN.md, PROGRESS.md, research.md, initial-codebase-analysis.md, then execute Phase 0."

---

## Milestones

| # | Phase | Model | Status | Branch | PR | Gate |
|---|-------|-------|--------|--------|----|------|
| — | Planning & docs (PRD/PLAN/CONTEXT/research/ADRs/data) | Opus | ✅ | main | — | n/a |
| 0 | Foundation, docs & skeleton | Sonnet | ⬜ | | | |
| 1 | Statistical core (correctness anchor) | Opus 4.8 | ⬜ | | | |
| 2 | Market data + scan → pairs table | Opus 4.8 | ⬜ | | | |
| 2.5 | Historical data ingest & validation | Sonnet | ⬜ | | | |
| 3 | Pair detail + 3-panel charts | Sonnet | ⬜ | | | |
| 4 | Live Manual Trading (new feature) | Sonnet | ⬜ | | | |
| 5a | Live trading engine (execution core) | Opus 4.8 | ⬜ | | | |
| 5b | Live trading UI | Sonnet | ⬜ | | | |
| 6 | Real-time simulation | Opus 4.8 | ⬜ | | | |
| 7 | Fast-forward simulation | Sonnet | ⬜ | | | |
| 8 | Walk-forward backtest | Sonnet | ⬜ | | | |
| 9 | Telegram integration | Sonnet | ⬜ | | | |
| 10 | Hardening, arch review & deploy prep | Opus 4.8 | ⬜ | | | |

---

## Per-Phase Acceptance Checklist
*(Copy the relevant block into the phase PR description; tick as completed.)*

```
Phase N — <name>
[ ] Implemented per PRD feature(s): __________
[ ] Unit tests pass
[ ] Integration tests pass (mocked dYdX/Telegram where applicable)
[ ] Playwright E2E pass (if UI)
[ ] /code-review ultra run, findings addressed
[ ] PROGRESS.md updated
[ ] Committed on phase-N-<name>, PR opened & merged
```

---

## Decisions Log (pointers)
- ADR-0002 — Option-B algorithm (intercept, stop-loss |Z|≥4.0 + 3×half-life, exit |Z|<0.5, half-life cap 72h)
- ADR-0003 — DB-backed state (no flat files)
- ADR-0004 — Exchange-registry + approval-gate abstractions
- ADR-0005 — Single driver agent per phase; manual model switch (`/clear` + `/model`)
- ADR-0006 — Reuse historical data; ingest `dydx` + `dydx_extended` into gitignored `data/` with validation

## Carry-Over Notes / Open Items
- `gh auth login` must be completed before opening issues/PRs.
- Rotate the exposed secrets from the old reference `.env` files before wiring a fresh `.env` (Phase 0).
- Data ingest (Phase 2.5): existing data has flat / zero-volume candles needing cleaning; `data/dydx` and `data/dydx_extended` are disjoint (~41 markets, no dedup needed).
