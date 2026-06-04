# statsArbBot — Implementation Plan (PLAN.md)

**Status:** Draft v1 · **Date:** 2026-06-01
**Companion docs:** `PRD.md` (what & why), `research.md` (quant evidence), `initial-codebase-analysis.md` (codebase map), `CONTEXT.md` (domain glossary), `docs/adr/` (decisions)

> This is the *execution roadmap*. Requirements live in `PRD.md`; this document says **how** we build and verify them.

---

## 1. Principles

- **Vertical slicing:** every phase delivers a working, tested, end-to-end increment — not a horizontal layer.
- **Integrate early, seek feedback often.**
- **Plan → Implement → Test → Commit** per phase. A phase is *done* only when its gate (unit + integration + Playwright E2E where UI exists) passes.
- **Many right-sized sub-phases** to keep each implementation session's context small — but not over-divided.
- **DB-backed state everywhere** — no flat-file live state.
- **Pure, isolated statistical core** — one source of algorithmic truth, reused by live / sim / FF / backtest.
- **Abstractions for swap-ability** — exchange registry (dYdX only implemented) and approval gate (stub → Telegram).

---

## 2. Tech Stack

**Backend:** Python 3.12 · FastAPI (async) · Uvicorn · Prisma ORM (async) · PostgreSQL 16 · `dydx-v4-client` · pandas/numpy/statsmodels · APScheduler · `python-telegram-bot` v20+.
**Frontend:** Next.js 14 (App Router, TS) · Tailwind (pure, no component lib) · SWR · `lightweight-charts` v5 · Recharts.
**Testing:** pytest · pytest-asyncio · pytest-mock · Jest + RTL · Playwright.
**Infra:** Docker Compose (postgres + api + ui).

**UI theme tokens (preserve exactly):** bg `#0a0b0d` · card `#12141a` · border `#21262d` · muted `#8b949e` · text `#e4e6ea` · green `#00d4a1` · red `#ff4757` · yellow `#ffd32a` · blue `#4a90e2`.

---

## 3. Target Directory Structure

```
statsArbBot/
├── docker-compose.yml
├── PRD.md  PLAN.md  CONTEXT.md  research.md  initial-codebase-analysis.md
├── docs/adr/                       # Architecture Decision Records
├── backend/
│   ├── app.py                      # FastAPI factory + lifespan
│   ├── auth.py                     # passcode + JWT
│   ├── config.py                   # constants (ZSCORE_THRESH, STOP_LOSS_ZSCORE=4.0, EXIT_ZSCORE=0.5, MAX_HALF_LIFE=72, ...)
│   ├── statcore/                   # PURE statistical engine (Phase 1)
│   │   ├── cointegration.py        # Engle-Granger, OLS hedge ratio + intercept
│   │   ├── spread.py               # spread = S1 - β·S2 - α
│   │   ├── halflife.py             # Ornstein-Uhlenbeck half-life
│   │   ├── zscore.py               # rolling Z-score
│   │   └── signals.py              # entry/exit/stop decision logic
│   ├── exchanges/                  # registry + dydx client; binance/hyperliquid stubs
│   ├── marketdata/                 # candles, price matrix, collateral
│   ├── scan/                       # scan orchestration + dual-write
│   ├── trading/                    # BotAgent, entry, exit, abort, approval-gate interface
│   ├── simulation/                 # engine, executor (cost model), scheduler, realtime feed
│   ├── replay/                     # fast-forward engine
│   ├── backtest/                   # walk-forward engine + scripts
│   ├── telegram/                   # bot + commands (Phase 9)
│   ├── db/                         # prisma client, writers, models
│   ├── routers/                    # live, scan, pairs, manual, sim, ff, backtest, exchange
│   └── tests/                      # unit + integration
├── ui/
│   ├── app/                        # login, dashboard, pair detail, backtest routes, api/proxy, api/auth
│   ├── components/                 # tables, charts, controls, manual-trade, slider, modals
│   ├── lib/api.ts                  # typed API client
│   ├── middleware.ts               # auth guard
│   └── e2e/                        # Playwright specs
├── data/                           # gitignored — historical CSVs copied from reference (dydx + dydx_extended)
└── prisma/schema.prisma
```

---

## 4. Phases & Gates

> Each phase: branch `phase-N-<name>` → implement → tests green → commit → PR → merge. Mid-phase defects → GitHub issue → fix → reference in commit/PR.

### Phase 0 — Foundation, Docs & Skeleton
**Do:** git init + connect `github.com/sauravs/statsArbBot`; `.gitignore`; rotate exposed secrets into fresh `.env`/`.env.example`. Write `PRD.md`, `PLAN.md`, `CONTEXT.md`, seed `docs/adr/`. Scaffold Docker Compose (postgres+api+ui), FastAPI factory + lifespan, Next.js app, Tailwind theme tokens, Prisma skeleton, **auth** (passcode + JWT + middleware + `/api/proxy`).
**Gate:** `docker compose up` boots all 3 services; login → empty dashboard; DB connects + migrates; Playwright smoke (login→dashboard).

### Phase 1 — Statistical Core *(correctness anchor)*
**Do:** implement `statcore/` (Engle-Granger, OLS hedge ratio **with intercept**, OU half-life, rolling Z-score, spread, signal logic) with all four Option-B changes.
**Gate:** unit tests assert numeric parity against reference data (`2_cointegrated_pairs.csv`, `3_backtest_file.csv`) within tolerance. Isolated on purpose — highest-risk code, validated before anything consumes it.

### Phase 2 — Market Data + Scan → Pairs Table *(first user-visible slice)*
**Do:** dYdX v4 data layer (markets, candles paginated + 429-retry + concurrency-limited, price matrix, collateral); scan orchestration (background async, progress streaming, **CSV + `CointScanResult` dual-write**, no race conditions); `/api/scan`, `/api/pairs`; PairsTable + scan button + progress UI.
**Gate:** scan from UI → pairs render; survive reload (DB). Unit + integration + Playwright E2E.

### Phase 2.5 — Historical Data Ingest & Validation *(feeds Phases 7 & 8)*
**Do:** copy existing dYdX CSVs (`dydx/` + `dydx_extended/`, OHLCV + funding) from the reference folder into the gitignored repo `data/` dir; **validation/cleaning pass** (drop/flag zero-volume & flat candles, detect gaps, enforce per-market minimum coverage); seed `OhlcvCache`. Port the prototype's `01_download_data.py` as a reproducible refresh script (not run now). *(See ADR-0006.)*
**Gate:** ingest populates `OhlcvCache`; validation report shows cleaned row counts and rejected bars per market; unit tests cover the cleaning rules.

### Phase 3 — Pair Detail + 3-Panel Charts
**Do:** pair OHLCV + spread + Z-score series endpoint; pair detail route with 3-panel `lightweight-charts` (normalized overlay / spread+σ bands / Z-score+thresholds + entry/exit markers).
**Gate:** click pair → all three panels render correctly. Unit + Playwright E2E.

### Phase 4 — Live Manual Trading *(new headline feature)*
**Do:** `ManualTrade` table; single-handle Z-threshold slider (0.5–4.0) re-filtering active signals live; "Record Manual Trade" button on active-signal pairs only; capital-allocation modal; separate Manual Trades section with mark-closed + P&L; manual-trade CRUD + close API.
**Gate:** set threshold → active pairs show button → record → appears (OPEN) → close → P&L computed (CLOSED). Integration + Playwright E2E.

### Phase 5a — Live Trading Engine (execution core)
**Do:** `BotAgent` atomic two-leg executor (preserve failsafe + CODE-RED); order placement/queries/cancel/abort via `dydx-v4-client`; entry scan (collateral guard, sides) + exit manager (`|Z|<0.5`, `|Z|≥4.0`, `3×half_life` time-stop, reconciliation, orphaned-leg handling); DB-backed trade state; `LiveSession`/`LiveTrade` with **real P&L**; **stub approval gate**.
**Gate:** testnet forward_test — entry opens, exit/stop closes, recorded with P&L. Integration tests w/ mocked dYdX.

### Phase 5b — Live Trading UI
**Do:** OpenTradesTable, BotControls (activate/deactivate), AccountCard, PortfolioStatus, TradeHistoryPanel, mode tabs.
**Gate:** UI reflects engine state; controls work. Playwright E2E.

### Phase 6 — Real-Time Simulation
**Do:** DB-backed `SimulationEngine` (stateless across ticks, restorable) with **proper rolling Z-score**; cost model (slippage/fee/funding); APScheduler ticks; realtime price feed; restart re-registration; sim UI (create/pause/resume/stop/topup).
**Gate:** session ticks → virtual trades on real signals → positions/PnL/equity update. Integration + Playwright E2E.

### Phase 7 — Fast-Forward Simulation
**Do:** `FastForwardReplayEngine` (N× historical replay) reusing Phase-6 engine; progress; `SavedFFSimulation` aggregates; FF UI (list/run/detail/saved).
**Gate:** FF run completes over a date range → saved results render. Integration + Playwright E2E.

### Phase 8 — Walk-Forward Backtest
**Do:** backtest engine (90d scan / 30d trade, S1–S4); subprocess orchestration w/ progress/pause/stop; partial save + resume; Strategy CRUD + rank recompute; backtest UI (page, comparison, create, reports).
**Gate:** backtest completes → ranked strategies + equity curves + reports; pause/stop/resume work. Integration + Playwright E2E.

### Phase 9 — Telegram Integration
**Do:** replace stub gate with real `python-telegram-bot` v20 approval flow wired into entry/exit; commands `/status /balance /positions /pairs /cancel /activate /deactivate` (**fix `connect_dydx` bug**).
**Gate:** signal → Telegram prompt → approve/reject/timeout → executes/skips; commands return live data. Integration tests w/ mocked Telegram.

### Phase 10 — Hardening, Architecture Review & Deploy Prep
**Do:** run `improve-codebase-architecture` skill; address findings; update ADRs; full regression; security review (confirm secrets rotated); AWS EC2 (cron+venv) deployment docs (documented, not executed).
**Gate:** all suites green; review clean.

---

## 5. Verification Strategy

| Layer | Tooling | Applies to |
|---|---|---|
| Unit | pytest / Jest | every phase |
| Integration | FastAPI TestClient + mocked dYdX/Telegram | phases with API |
| E2E | Playwright | every phase with UI |
| Numeric parity | pytest vs reference CSVs | Phase 1 |
| Live/sim validation | dYdX **testnet** | Phases 5–7 before production |
| Full regression + arch + security review | all suites + skill | Phase 10 |

---

## 6. Git / GitHub Workflow
- Repo: `github.com/sauravs/statsArbBot`. Branch per phase (`phase-N-<name>`) → PR → merge.
- Commit messages end with the required `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.
- PR bodies end with the Claude Code attribution line.
- Mid-phase defects tracked as GitHub issues, referenced in the fixing commit/PR.

### 6.1 Code-review findings → issue tracking
Every phase ends with a code review (`/code-review` or `/code-review ultra`). For each finding **we accept**:
- **Accepted but *deferred*** (not fixed in the current PR) → **open a GitHub issue** (label `code-review`), titled with the defect and referencing the source PR/commit. This is the durable, cross-session record — a fresh session should check open `code-review` issues before starting a phase. Close the issue from the commit/PR that fixes it.
- **Accepted and *fixed in the same PR*** → no separate issue required; record it in the PR description/comment and the fixing commit message (the merge commit is the permanent trail). Optionally file a *closed* `code-review` issue if a searchable audit entry is wanted.
- **Refuted / rejected** findings need no issue.

Rationale: open issues track outstanding work future sessions must find; already-fixed findings live in the PR history. (See PR #1 for the Phase 0 example: six findings, all fixed in-PR and recorded in the PR comment rather than as issues.)

### 6.2 Bugs found during testing / operation → issue tracking
Phases are complete; from here, work is largely **bug fixes found while running the app** (local testing or live). The convention (so a fresh session inherits a complete, searchable bug history via `gh issue list --label bug`):
1. **Triage, then agree.** The operator describes the behaviour; the agent and operator **mutually confirm it's a real bug** (not expected behaviour, config, or a testnet quirk) before filing — don't file expected behaviour as bugs.
2. **Open a GitHub issue** with `gh issue create --label bug`, titled with the defect, body containing **repro steps + expected vs actual + affected files**. (The `bug` label exists; `code-review` is reserved for review findings.)
3. **Fix on its own branch** named `fix-<slug>` (one branch + PR per bug, separate from any phase branch), and reference the issue in the PR/commit so it **auto-closes on merge** (`Closes #NN`).
4. The agent **always confirms with the operator before opening an issue or a fix PR**; PRs are merged manually by the operator (see PROGRESS "Current Position").

Rationale: a durable, labelled issue trail lets future sessions run `gh issue list` and instantly understand the app's known problems, history, and fixes — extending §6.1's mechanism from review findings to runtime bugs.

---

## 7. Session / Context Notes
- Authoritative context for any fresh session: `research.md` + `initial-codebase-analysis.md` + `PRD.md` + this `PLAN.md`. Live status lives in `PROGRESS.md` — read it first to see what's done and what's next.
- Run each phase (or sub-phase) in its own session to keep context lean.

### 7.1 Per-Phase Session Ritual *(manual — the operator performs these; the agent does not auto-switch model or auto-clear context)*
At the start of each phase:
1. `/clear` — reset context to a clean window.
2. `/model opus` — **decision: Opus 4.8 for all phases** (no per-phase switching; see §7.2).
3. Prompt: "Read `PRD.md`, `PLAN.md`, `PROGRESS.md`, `research.md`, `initial-codebase-analysis.md`, then execute Phase N."
At the end: update `PROGRESS.md`, commit on `phase-N-<name>`, open PR via `gh`, run `/code-review ultra`, merge.

### 7.2 Model Selection
> **DECISION (locked): use Opus 4.8 for every phase.** No per-phase switching. Rationale: this is a correctness-critical financial system; the per-token premium on mechanical phases is outweighed by fewer bug-fix cycles and a single, simpler ritual. Reviews use `/code-review ultra` regardless.

The table below is retained only as reference for the *relative* risk/complexity of each phase (e.g. where to apply extra care and test depth) — it no longer drives model choice.

| Phase | Relative risk | Rationale |
|---|---|---|
| 0 Foundation | Low | Mechanical scaffold/auth |
| **1 Statistical core** | **High** | Highest-risk math; must match ground truth — extra test depth |
| **2 Market data + scan** | **High** | Async concurrency, rate limits, dual-write (race-condition zone) |
| 2.5 Data ingest/validation | Low | Mechanical cleaning rules |
| 3 Pair detail + charts | Low | Well-specified UI/charting |
| 4 Live Manual Trading | Low | Straightforward CRUD + UI |
| **5a Live trading engine** | **High** | Atomic execution, failsafe, real P&L, real money |
| 5b Live trading UI | Low | Tables, controls, wiring |
| **6 Real-time simulation** | **High** | Stateless-engine correctness (prototype z-score bug lived here) |
| 7 Fast-forward sim | Medium | Reuses Phase-6 engine; orchestration |
| 8 Walk-forward backtest | Medium | Subprocess orchestration + UI |
| 9 Telegram | Medium | Approval-gate wiring into entry/exit is the delicate part |
| 10 Hardening/arch review | **High** | Cross-cutting reasoning + security |

---

## 8. Out of Scope (this rewrite)
Binance/Hyperliquid impl; AI/LangGraph tables; WebSocket feed; Johansen/KSS; HMM regime filter; Kalman hedge ratio; log-prices; Z-proportional sizing; live AWS deploy.
