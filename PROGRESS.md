# statsArbBot — Progress Tracker

**Living status file. Read first at the start of every session.** Update at each phase boundary.
Companion docs: `PRD.md` (what), `PLAN.md` (how + per-phase model in §7.2), `docs/adr/` (decisions).

- **Status legend:** ⬜ not started · 🟡 in progress · ✅ done (gate passed + merged) · 🔴 blocked
- **Gate = phase complete only when:** unit + integration + (UI) Playwright tests pass → `/code-review ultra` → PR merged.

---

## Current Position

- **Phase in progress:** Phase 0 — Foundation, docs & skeleton (branch `phase-0-foundation`; gate verified, awaiting PR review + merge).
- **Model:** **Opus 4.8 for all phases** (locked; no switching — see PLAN.md §7.2).
- **Next action:** merge the Phase 0 PR, then Phase 1 — `/clear`, `/model opus`, then "Read PRD.md, PLAN.md, PROGRESS.md, research.md, initial-codebase-analysis.md, then execute Phase 1."

---

## Milestones

*Model = Opus 4.8 for all phases (locked).*

| # | Phase | Status | Branch | PR | Gate |
|---|-------|--------|--------|----|------|
| — | Planning & docs (PRD/PLAN/CONTEXT/research/ADRs/data) | ✅ | main | — | n/a |
| 0 | Foundation, docs & skeleton | 🟡 | phase-0-foundation | [#1](https://github.com/sauravs/statsArbBot/pull/1) | gate verified except full `docker compose up` (disk full — see below) |
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
- Secrets: **use the existing `.env` as-is for development** (testnet — low risk; operator's decision). Generate fresh dYdX keys / Telegram token / dashboard password **only before switching to `production` (mainnet) mode**. Phase 0 added `DASHBOARD_JWT_SECRET` (placeholder; rotate before production).
- Data ingest (Phase 2.5): existing data has flat / zero-volume candles needing cleaning; `data/dydx` and `data/dydx_extended` are disjoint (~41 markets, no dedup needed).

### Phase 0 outcomes / decisions
- **Scaffold layout:** `backend/` (FastAPI, entrypoint `app:app`) + `ui/` (Next 14) + `docker-compose.yml`. Prisma lives at `backend/prisma/` (not repo root) so it's inside the api Docker build context — pragmatic deviation from the aspirational PLAN §3 tree.
- **Auth split:** session JWT (signed via `jose`) lives in the Next.js tier — login route mints it, `middleware.ts` + `/api/proxy` + `/api/auth/check` verify it. The browser never calls FastAPI directly; the proxy injects a shared `X-API-Key` that `backend/auth.py:require_api_key` validates. Upgrades the prototype's plain `token==password` cookie to a real signed JWT (PRD F1.2).
- **Trading constants** centralised in `backend/config.py` with the four Option-B defaults (entry 1.5 / exit 0.5 / stop 4.0 / half-life cap 72h) — consumed by statcore in Phase 1.
- **Initial migration** `backend/prisma/migrations/0001_init` committed (enums `Exchange`/`TradingMode` + `BotConfigHistory` skeleton). Domain models added per phase.
- **Heads-up for next session:** the local Docker `postgres_data` volume previously held the *prototype's* full schema; Phase 0 reset `public` to apply our clean migration. If you see stale tables, `docker compose down -v` to wipe.
- **Gate verification (Phase 0):** backend `pytest` 4/4 ✓ · `prisma migrate deploy` creates `BotConfigHistory` ✓ · `next build` compiles all routes+middleware ✓ · Playwright smoke (redirect→login, wrong-passcode reject, login→dashboard) 3/3 ✓ · `docker compose config` valid ✓.
