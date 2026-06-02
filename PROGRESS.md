# statsArbBot — Progress Tracker

**Living status file. Read first at the start of every session.** Update at each phase boundary.
Companion docs: `PRD.md` (what), `PLAN.md` (how + per-phase model in §7.2), `docs/adr/` (decisions).

- **Status legend:** ⬜ not started · 🟡 in progress · ✅ done (gate passed + merged) · 🔴 blocked
- **Gate = phase complete only when:** unit + integration + (UI) Playwright tests pass → `/code-review ultra` → PR merged.

---

## Current Position

- **Phase in progress:** _none — planning complete, implementation not yet started (awaiting go-ahead)_
- **Model:** **Opus 4.8 for all phases** (locked; no switching — see PLAN.md §7.2).
- **Next action:** Phase 0 — `/clear`, `/model opus`, then "Read PRD.md, PLAN.md, PROGRESS.md, research.md, initial-codebase-analysis.md, then execute Phase 0."

---

## Milestones

*Model = Opus 4.8 for all phases (locked).*

| # | Phase | Status | Branch | PR | Gate |
|---|-------|--------|--------|----|------|
| — | Planning & docs (PRD/PLAN/CONTEXT/research/ADRs/data) | ✅ | main | — | n/a |
| 0 | Foundation, docs & skeleton | ⬜ | | | |
| 1 | Statistical core (correctness anchor) | ⬜ | | | |
| 2 | Market data + scan → pairs table | ⬜ | | | |
| 2.5 | Historical data ingest & validation | ⬜ | | | |
| 3 | Pair detail + 3-panel charts | ⬜ | | | |
| 4 | Live Manual Trading (new feature) | ⬜ | | | |
| 5a | Live trading engine (execution core) | ⬜ | | | |
| 5b | Live trading UI | ⬜ | | | |
| 6 | Real-time simulation | ⬜ | | | |
| 7 | Fast-forward simulation | ⬜ | | | |
| 8 | Walk-forward backtest | ⬜ | | | |
| 9 | Telegram integration | ⬜ | | | |
| 10 | Hardening, arch review & deploy prep | ⬜ | | | |

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
- ✅ `gh` authenticated (account `sauravs`, scopes incl. `repo`+`workflow`) — issues/PRs ready.
- Secrets: **use the existing `.env` as-is for development** (testnet — low risk; operator's decision). Generate fresh dYdX keys / Telegram token / dashboard password **only before switching to `production` (mainnet) mode**.
- Data ingest (Phase 2.5): existing data has flat / zero-volume candles needing cleaning; `data/dydx` and `data/dydx_extended` are disjoint (~41 markets, no dedup needed).
