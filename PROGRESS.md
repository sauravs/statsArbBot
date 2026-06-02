# statsArbBot — Progress Tracker

**Living status file. Read first at the start of every session.** Update at each phase boundary.
Companion docs: `PRD.md` (what), `PLAN.md` (how + per-phase model in §7.2), `docs/adr/` (decisions).

- **Status legend:** ⬜ not started · 🟡 in progress · ✅ done (gate passed + merged) · 🔴 blocked
- **Gate = phase complete only when:** unit + integration + (UI) Playwright tests pass → `/code-review ultra` → PR merged.

---

## Current Position

- **Phase in progress:** Phase 1 — Statistical core (branch `phase-1-statcore`; gate passed locally, awaiting PR review + merge). Phase 0 merged (PR #1).
- **Model:** **Opus 4.8 for all phases** (locked; no switching — see PLAN.md §7.2).
- **Next action:** open the Phase 1 PR, run `/code-review ultra`, merge. Then Phase 2 — `/clear`, `/model opus`, then "Read PRD.md, PLAN.md, PROGRESS.md, research.md, initial-codebase-analysis.md, then execute Phase 2."

---

## Milestones

*Model = Opus 4.8 for all phases (locked).*

| # | Phase | Status | Branch | PR | Gate |
|---|-------|--------|--------|----|------|
| — | Planning & docs (PRD/PLAN/CONTEXT/research/ADRs/data) | ✅ | main | — | n/a |
| 0 | Foundation, docs & skeleton | ✅ | phase-0-foundation | [#1](https://github.com/sauravs/statsArbBot/pull/1) | ✅ gate fully verified (incl. `docker compose up`) — merged |
| 1 | Statistical core (correctness anchor) | 🟡 | phase-1-statcore | | ✅ gate passed locally (29/29 pytest; parity to ~1e-9) — see below |
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
- ADR-0007 — statcore parity validated in legacy mode against committed reference fixtures; Option-B asserted separately

## Carry-Over Notes / Open Items
- ✅ `gh` authenticated (account `sauravs`, scopes incl. `repo`+`workflow`) — issues/PRs ready.
- Secrets: **use the existing `.env` as-is for development** (testnet — low risk; operator's decision). Generate fresh dYdX keys / Telegram token / dashboard password **only before switching to `production` (mainnet) mode**. Phase 0 added `DASHBOARD_JWT_SECRET` (placeholder; rotate before production).
- Data ingest (Phase 2.5): existing data has flat / zero-volume candles needing cleaning; `data/dydx` and `data/dydx_extended` are disjoint (~41 markets, no dedup needed).

### Phase 0 outcomes / decisions
- **Scaffold layout:** `backend/` (FastAPI, entrypoint `app:app`) + `ui/` (Next 14) + `docker-compose.yml`. Prisma lives at `backend/prisma/` (not repo root) so it's inside the api Docker build context — pragmatic deviation from the aspirational PLAN §3 tree.
- **Auth split:** session JWT (signed via `jose`) lives in the Next.js tier — login route mints it, `middleware.ts` + `/api/proxy` + `/api/auth/check` verify it. The browser never calls FastAPI directly; the proxy injects a shared `X-API-Key` that `backend/auth.py:require_api_key` validates. Upgrades the prototype's plain `token==password` cookie to a real signed JWT (PRD F1.2).
- **Trading constants** centralised in `backend/config.py` with the four Option-B defaults (entry 1.5 / exit 0.5 / stop 4.0 / half-life cap 72h) — consumed by statcore in Phase 1.
- **Initial migration** `backend/prisma/migrations/0001_init` committed (enums `Exchange`/`TradingMode` + `BotConfigHistory` skeleton). Domain models added per phase.
- **Heads-up for next session:** the local Docker `postgres_data` volume previously held the *prototype's* full schema; Phase 0 reset `public` to apply our clean migration. If you see stale tables, `docker compose down -v` to wipe.
- **Gate verification (Phase 0) — FULLY PASSED:** backend `pytest` 4/4 ✓ · `next build` compiles all routes+middleware ✓ · **`docker compose up --build` boots all 3 services** (postgres healthy, api + ui up) ✓ · migration runs in-container (`BotConfigHistory` created) ✓ · authed `/api/system/health` reports `database: connected`, missing key → 401 ✓ · full UI→proxy→API→DB chain verified via JWT login cookie (login 200; proxy with cookie → `connected`; without cookie → 401) ✓ · Playwright smoke (redirect→login, wrong-passcode reject, login→dashboard) 3/3 against the **containerized** UI ✓.
- **Docker recovery note:** the earlier disk-full crash corrupted Docker Desktop's containerd content store (`meta.db` + image blobs → I/O errors), wedging the daemon. Fixed by deleting the VM disk (`~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw`) and restarting Docker clean. Added `ui/.dockerignore` + `backend/.dockerignore` so build contexts stay small (the missing ui ignore was shipping `node_modules` + the 92MB Playwright browser into the image and helped exhaust the disk).

### Phase 1 outcomes / decisions
- **`backend/statcore/` package** — pure statistical engine, no DB/exchange/I/O. Modules: `cointegration.py` (Engle-Granger via `statsmodels.coint`, OLS hedge ratio **with intercept** by default, `analyze_pair` orchestrator), `spread.py` (`compute_spread` = S1−β·S2−α, `zero_crossings`), `halflife.py` (OU half-life), `zscore.py` (`rolling_zscore` + `latest_zscore`, sample std ddof=1, fixes the prototype's `0.02` approximation), `signals.py` (`evaluate_entry`/`evaluate_exit` with Option-B stop/exit/time-stop). Public API re-exported from `statcore/__init__.py`.
- **Parity strategy (ADR-0007):** validated in **legacy mode** (no intercept, β rounded to 1.29) against the MATIC/STX reference, reproducing the `Spread` and `ZScore` columns to ~1e-9 and matching coint t/p/crit, hedge ratio, and zero_crossings (43); half-life locked at 3.0. The four Option-B changes are asserted in **separate** tests. Reference CSVs committed as hermetic fixtures under `backend/tests/fixtures/` (the `Old Reference Resources/` tree is gitignored).
- **Edge cases:** half-life returns `nan` for non-mean-reverting series (slope `b ≥ −1e-9`, incl. fp-noise trends) and constant spreads (`add_constant(has_constant="add")`); `latest_zscore` returns `nan` on insufficient data / zero-variance windows.
- **Gate (Phase 1) — PASSED locally:** `pytest` 33/33 ✓ (29 statcore + 4 Phase-0 smoke, no regression). Isolated by design — no integration/UI this phase. Note: `np`/`pandas`/`statsmodels` numerics are version-sensitive; parity tests are the early-warning signal (local env: statsmodels 0.14.6, pandas 3.0.3, numpy 2.4.6).
- **Code review (`/code-review high`, 7 angles) — 8 findings, all addressed in-PR** (per PLAN §6.1; no separate issues since fixed in the same PR):
  1. *(correctness)* `analyze_pair` `pvalue_max` was dead above 0.05 (shadowed by hardcoded `is_significant`) → added `CointegrationTest.is_cointegrated(pvalue_max)`; filter now honours the configurable cutoff.
  2. *(correctness)* `evaluate_exit` ranked the time-stop above take-profit, mislabeling profitable reverted exits as `STOP_LOSS_TIME` → reordered to stop-z → take-profit → time-stop.
  3. *(correctness/testability)* config thresholds were frozen as import-time default args → now resolved at call time (default `None`), so config/slider/monkeypatch changes take effect.
  4. *(robustness)* non-finite `position_age_hours` now ignored so a bad clock can't mask the time-stop.
  5. *(doc)* corrected `zero_crossings` docstring re: exact-on-mean behaviour.
  6. *(altitude)* named the coint 5%-critical-value index (`_CRIT_VALUE_5PCT_INDEX`).
  - **Left as-is (judgment):** `latest_zscore` vs `rolling_zscore` formula duplication (the tail form is the efficient path; guarded by a 1e-12 parity test) and the `half_life` `b >= -1e-9` epsilon (documented; rejects only ~7e8-period non-reversion that the 72h cap would reject anyway).
