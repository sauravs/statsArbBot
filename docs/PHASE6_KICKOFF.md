# Phase 6 — kickoff prompt for the next session

**Date:** 2026-08-26 · **Status:** the search on the current signal is CLOSED.
This document is the **starting prompt** for the next agent session. Paste §"THE PROMPT"
verbatim. §1–§4 are the evidence behind it; read them before deciding to spend money or time.

---

## 0. TL;DR — what is actually left

**Almost nothing, and the reason is arithmetic rather than fatigue.**

Gate B3's multiplicity-corrected bar is `sr_star = 1.839`. Entry 4.0's window Sharpe is
**0.26**. That is a **7.1× gap in risk-adjusted performance**. No parameter refinement
moves a Sharpe 7×; tweaks move it 10–30%. Reproduced independently this session from the
live `n_trials = 72` and trial-SR sd 0.762 — it lands on the documented 1.839 exactly.

Worse, **the search is self-defeating**: `n_trials` is computed *dynamically* from the
qualifying saved runs (`backend/stats/significance.py:41-43`), so every additional config
raises the bar it must clear.

| `n_trials` | `sr_star` | × needed vs 0.26 |
|---|---|---|
| 72 (today) | 1.839 | **7.1×** |
| 92 | 1.906 | 7.3× |
| 122 | 1.982 | 7.6× |
| 172 | 2.070 | 8.0× |

**Running more variants of the same idea actively makes the problem harder.** That single
table is the strongest argument for stopping the sweep-style search.

Exactly **one** cheap test remains honestly open (§2). Everything else that could work is a
**different signal**, not a refinement (§3).

---

## 1. What is closed, and why (do not re-litigate)

| Line of attack | Verdict |
|---|---|
| Exit \|Z\| | noise lever ($2,087 ± $212 across 0.05–0.50) |
| Entry \|Z\| ≤ 4.0 | dominant lever; measured OOS; see §2 for the one open edge |
| p-value | potent below 0.05, saturates (hard-wired 95% t-stat gate); keep 0.01 |
| Half-life cap | **inert** — only 0.0–0.2% of entry-4.0 trades exceed 48h |
| Stop \|Z\| | risk/return see-saw; fires on only 1.6–4.7% of trades |
| Scan/trade windows | swept (`window-sweep` family) |
| Liquidity / universe filters | **refuted** — gross lives in the thinnest markets (+$2,554 → −$183 at ≥$100k/hr) |
| Entry × per-leg size | mechanism real (impact/trade ~constant, count is the lever); **fails DSR** |
| Executable concurrency | needs **20–100 simultaneous positions**; capped to human scale it goes negative, and best-\|Z\| ordering lands inside a random-admission null |
| Funding-carry-aware selection | **refuted by its own hindsight ceiling** — perfect foresight on the funding sign is *worse* than no filter (+$2,346 → +$193; +$15,787 → **−$226**), because adverse carry **marks** the profitable trades (6.7× the gross, 54× at $1k/leg) |

Full write-ups: `docs/strategy.md`, `docs/QA.md` (2026-08-01 and 2026-08-03 entries),
`docs/PHASE2_STRATEGY_PLAN.md` §1/§4/§7, `docs/PHASE4_TASKC_PLAN.md`.

---

## 2. The ONE cheap thing still open: entry |Z| > 4.0

**Why it is open, stated fairly.** Phase-4 measured net rising **monotonically** at *both*
per-leg sizes, and 4.0 is the **edge of the tested grid**:

| Entry | OOS @ $100/leg | OOS @ $1,000/leg | Trades |
|---|---|---|---|
| 3.5 | −$1,246 | −$48,872 | ~7,650 |
| 3.75 | +$911 | −$8,374 | ~3,710 |
| **4.0** | **+$2,346** | **+$15,787** | **~1,510** |

That is a **boundary solution**. The documented reason for never testing higher
(`PHASE4_TASKC_PLAN.md` §6) was *"phase-1 found net falling from 3.5 to 4.0"* — a
**purely in-sample** finding that **Phase-4 reversed out-of-sample**. So the rationale for
the exclusion no longer holds, and the region has never been measured.

**The blocker is a one-line cap:** `entry_threshold` is `le=4.0` at
`backend/routers/backtest.py:62` and `:95`.

**Pre-stated prediction (so the bar cannot move afterwards): it will fail B3, harder.**
Trade count is collapsing ~2.3× per 0.25 step (7,650 → 3,710 → 1,510), so expect **~600
trades at 4.5** and **~250 at 5.0**. Fewer trades ⇒ *worse* DSR and *worse* window
concentration, which are the two things that already fail. Net may well rise; **net is not
the binding gate.**

**Worth doing anyway?** Yes — but only to *close the boundary honestly*, ~2h of prod
compute, and only if the operator wants the grid finished rather than left open at its
best point. It is not a route to a "yes".

---

## 3. What would genuinely count as new (all untested, all bigger than a sweep)

These change **the signal**, which is what `PHASE2_STRATEGY_PLAN.md` §7 actually asks for.
Each needs its own plan and engine work; none is a campaign parameter.

1. **Dynamic hedge ratio.** Everything to date uses a **static OLS β** re-fit per formation
   window (`statcore/cointegration.py:105`). A Kalman-filtered / rolling β makes the spread
   itself adaptive. **This changes what is being traded**, not how it is filtered.
2. **Bar resolution.** Hourly only (`CANDLE_RESOLUTION=1HOUR`). Admitted half-lives are
   5–28h, so hourly is defensible — but 4h/daily bars with a longer formation window is a
   different regime, and the deep-history archive supports it.
3. **Multi-leg / factor-neutral construction.** Strictly pairwise today. Baskets or
   PCA-residual portfolios are a different estimator with different degrees of freedom.

**Honest caveat that applies to all three:** they still face `sr_star ≈ 1.84` and rising.
A new signal's runs *add* to `n_trials` under the current pooled computation. Scoping DSR
to an independent, **pre-registered** hypothesis family is methodologically defensible —
but it must be pre-registered **before** running, never chosen after seeing the result.
Treat any post-hoc re-scoping as moving the bar.

---

## 4. State of the world (verify, don't assume)

- **Prod:** `production` @ `2e37589`, `ENVIRONMENT=testnet`, honest cost flags ON,
  **0 sim sessions**, nothing trading. `main` == `production`.
- **Inventory:** 75 phase-1 + 27 phase-2 hyperliquid strategies. **Never delete a row.**
- **Costs are honest everywhere now** — backtest, real-time sim *and* fast-forward share
  `simulation/cost_map.py`; the sim also accrues real funding (it charged **none** before
  2026-08-01).
- **Best DSR across all 72 saved runs = 0.031** vs a 0.95 bar. Nothing is close.
- **Deep history** (2024-01→) is **prod-only**, backfilled from
  `s3://hyperliquid-archive/asset_ctxs/YYYYMMDD.csv.lz4` (requester-pays) via
  `ops/hl_deep_backfill.py`. The live `/info` API caps at ~5k candles (~7 months).
- **Gotchas:** `SCAN_DATA_SOURCE` resets to `dydx` on every api restart — re-POST
  `/api/system/data-source` → `hyperliquid` *before* creating anything, and note that the
  switch returns `pairs_cleared: true`, so a **fresh scan is required**. Monitor long runs
  via `psql`, not HTTP (CPU-bound scan saturates the event loop on 2 vCPU).
- **Universe reality check:** the last prod scan found **12 pairs from 595 tested**, only
  **2** at p ≤ 0.01, max \|Z\| **1.55**. Any live/paper exercise starts from that.

---

## THE PROMPT

> ROLE: Senior QUANT + full-stack engineer on statsArbBot (Hyperliquid pairs-trading /
> stat-arb). FIRST load: `CONTEXT.md`, `.claude/CLAUDE.md`, `docs/PHASE6_KICKOFF.md` (this
> file — §0–§4 are the standing evidence), `docs/strategy.md` (esp. the final two sections),
> `docs/QA.md` (2026-08-01 and 2026-08-03 entries), `docs/PHASE2_STRATEGY_PLAN.md` §1.
>
> ════ STANDING CONTEXT — do NOT overturn, do NOT quietly erode ════
> The bot is **NO-GO for live trading, and the search on the current signal is CLOSED, not
> unfinished.** Every named line of attack is exhausted, including the last one
> (funding-carry-aware selection), which was refuted by its own hindsight ceiling: with
> *perfect foresight* on the funding sign, filtering is **worse** than not filtering
> (+$15,787 → −$226 at $1k/leg), because adverse carry **marks** the profitable trades.
>
> **The master fact:** gate B3's corrected bar is `sr_star = 1.839`; the best config's
> window Sharpe is **0.26** — a **7.1× gap**. `n_trials` is computed dynamically, so every
> extra config *raises* that bar (72→172 trials moves it 7.1×→8.0×). **No parameter
> refinement closes a 7× Sharpe gap.** If you find yourself proposing another sweep,
> re-read this paragraph.
>
> ════ YOUR TASK ════
> Do **not** start work. First tell me, in one page:
> 1. Whether you agree the search is closed, and if not, exactly which pre-registered,
>    falsifiable test would change the verdict — with its predicted outcome stated *before*
>    running.
> 2. Your recommendation among: **(a)** close the entry-\|Z\| boundary by testing 4.25/4.5/5.0
>    (needs the `le=4.0` cap at `backend/routers/backtest.py:62,95` raised; ~2h prod compute;
>    §2 predicts it fails B3 *harder* because trade count collapses ~2.3× per step);
>    **(b)** start ONE genuinely different signal from §3 (dynamic/Kalman hedge ratio is the
>    best-motivated), with a written plan and pre-registered DSR scoping *before* any run;
>    **(c)** stop the search and consolidate — the honest answer already exists and further
>    compute has negative expected value.
> 3. What you would need from me to proceed.
>
> State your recommendation plainly, with reasoning, and do not hedge. If (c) is right, say
> so — "we should stop" is a valid and valuable answer here, and the evidence supports it.
>
> ════ THE GATE (non-negotiable) ════
> Per unit of work: short-lived `feat-`/`fix-`/`docs-<slug>` branch off `main` → implement
> (TDD where code) → test e2e on the LOCAL DEV DOCKER STACK → PR (CI: backend·pytest +
> frontend·typecheck+build + e2e·playwright) → **explicit operator approval** → merge.
> Promotion `main`→`production` and ANY prod action (deploy, creating a sim session,
> launching a campaign) is a **separate** explicit OK. `ENVIRONMENT` stays `testnet`.
> `pg_dump` before any `prisma migrate deploy`. **NEVER delete a strategy row.** Ranking on
> in-sample net is forbidden. ASK BEFORE GUESSING on scope, criteria or data.
>
> Nothing in this session ships a live strategy or relaxes a gate.

---

## 5. Recommendation from the session that wrote this

**(c), with (a) as an optional two-hour tidy-up.**

The 7.1× gap is not a tuning problem, and the `n_trials` table shows more searching makes it
worse. Entry > 4.0 is the only genuinely open cell in the grid and it is cheap — but it is
*predicted to fail harder*, so it buys completeness, not hope. **(b)** is the only route that
could ever produce a "yes", and it is real project work (new estimator, new plan, new
pre-registration), not a sweep — it should be started deliberately or not at all.

The project has already produced its most valuable output: a defensible, well-evidenced
**no**, reached by testing the last hypothesis rather than assuming it.
