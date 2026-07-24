# Phase 2 — Strategy Plan (sub-phase A: recommendation, evidence-gated)

**Status:** DRAFT for operator approval. No code merged, no deploy, bot untouched.
**Date:** 2026-07-24
**Author:** Phase-2 planning pass (quant review + targeted probes).
**Scope:** This is sub-phase A. It recommends; it does not implement. Sub-phase B
(implementation) begins only after the operator approves the plan below. The
project's standing "ship end-to-end without asking" approval is **deliberately
overridden** for this work by an explicit plan-approval gate.

---

## 0. TL;DR verdict

**No existing or probed configuration clears the selection bar. Do not go live.**

- The best genuinely out-of-sample, real-taker-cost result is **entry |Z|≥3.5 at
  +$187 net across s2–s4**, which sits **inside the ±$212 noise floor** — statistically
  zero (established in the 2026-07-22 execution-economics work; re-confirmed here from
  the prod DB).
- The operator's hypothesis — *raise the liquidity floor to cut noise and gain edge* —
  is **refuted by a decisive probe**. The strategy's gross edge is **concentrated in the
  thinnest markets**. Filtering the backtest universe up to liquid names collapses gross
  from **+$2,554 to −$183 (≥$100k/hr) or +$44 (≥$1M/hr)**; because costs are per-trade,
  **net gets worse, not better, at every liquidity threshold tested.**
- A volatility filter shows the same trap: the surviving gross is either a noise-floor
  calm-tail (+$168 net) or a "hot-market" mirage whose mid-price gross is an artifact of
  the wide spreads real taker fills would actually pay.
- Root cause: the "+$2,554 OOS gross" is mid-price mean-reversion in illiquid/volatile
  alts. A taker paying real spreads — and, at manual size, real **market impact
  (first-order ≈0.2–0.5% per leg, 3–7× the entire modelled cost)** — cannot harvest it.

**An honest "not yet" is the outcome. §7 gives the concrete, testable path to a possible
"yes."**

---

## 1. The selection bar (pre-stated, numeric)

A configuration is recommendable for **manual, market-order (taker-only) trading** only
if it clears **all five** gates. These are fixed *before* looking at any candidate, to
avoid fitting the bar to the winner.

| # | Gate | Threshold |
|---|------|-----------|
| B1 | **Out-of-sample only** | Measured on spans whose window has **zero overlap** with the in-sample period 2026-03-01→2026-06-23. In-sample and overlapping rows are **inadmissible as evidence** (they are search output, not prediction). |
| B2 | **Real taker costs, every fill** | Fee **0.045%** + slippage **≥ the realistic per-market half-spread** (≥ measured mean 0.0316%; higher where the trades actually live), charged on all 4 fills/round-trip. Zero-cost and reduced-cost (0.02%) runs are diagnostic only, **never evidence of tradeable P&L**. |
| B3 | **Beats the noise floor with significance** | OOS net across s2–s4 must exceed the **±$212 (1σ) noise floor by ≥2σ → net ≥ +$424**, *or* pass a **Deflated-Sharpe test that survives correction for the 69-config search** at p<0.05. (+$187 fails.) |
| B4 | **Cross-span robustness** | Non-negative in a **majority of independent OOS spans** (≥2 of s2/s3/s4), not carried by one lucky span. |
| B5 | **Executable at real size** | Gross must survive a **first-order market-impact charge at the operator's actual per-leg size** (not $100 top-of-book). |

Rationale for B3's number: the 2026-07-22 analysis established the OOS net standard
error at ≈$212. A coin-flip result (+$187) is indistinguishable from zero; a *business*
must clear the flip by a real margin. B5 exists because every cost figure measured so
far assumes $100/leg at top-of-book — see §5.

---

## 2. Diagnosis of all saved strategies (prod DB, `data_source='hyperliquid'`)

Pulled live from prod (`strategies` table, 69 rows) and cross-checked against the
Phase-1 classifier `ui/lib/strategyTaxonomy.ts`. The classifier's two orthogonal axes —
**cost tier** (`ZERO`/`REDUCED`/`MODELLED`, from `taker_fee_pct`/`slippage_pct`) and
**span** (`IN_SAMPLE`/`OVERLAPS`/`OUT_OF_SAMPLE`, from the config's dates vs the
2026-03-01→06-23 window) — are the frame; this section builds on it, it does not
re-derive it.

### 2.1 The honest evidence set — 12 realistic rows, 11 losses

Applying the classifier's `realistic = (cost === MODELLED_COST) && (span === OUT_OF_SAMPLE)`
predicate to the 69 rows collapses them to exactly **12 admissible rows, of which 11 are
losses** (reproduced from prod, matching the taxonomy):

| Family | Rows (span) | Net | Read |
|---|---|---|---|
| entry-3.5 revalidation | reval-3.5 s2 / s3 / s4 | −$170 / −$1,313 / **+$948** | OOS sum **−$536**; only s4 positive → **fails B4** |
| entry-3.0 revalidation | reval-3.0 s2 / s3 / s4 | −$1,289 / −$3,334 / −$822 | strictly worse than 3.5 |
| z-stop | stop-3.75-s3 / stop-6.0-s3 | −$1,665 / −$1,291 | risk/return only, no edge |
| half-life | hl-24-s3 / hl-48-s3 | −$1,348 / −$1,326 | inert |
| ad-hoc entry-1.5 | sauravs test / demo-3 | −$1,872 / −$779 | low-Z, high-frequency bleed |

Everything green on the dashboard is either **in-sample** (single 2026-03-01→06-23
window — search output) or a **zero-cost counterfactual** (`cost-000*`, `cost000-e30*`:
fees+slippage=0). None is both realistic and out-of-sample. This is exactly what PR #217
surfaced, and the prod data confirms it.

### 2.2 Gross vs net, reconstructed from `backtest_trades` (verification)

The zero-cost OOS runs store true mid-price gross per trade. Aggregated from prod:

| Config | OOS gross = Σ(gross_pnl+funding) | Real-taker net (fee 0.045% + slip 0.0316%) |
|---|---|---|
| entry-3.5 | +$1,181 −$200 +$1,573 = **+$2,554** | **+$187** (7,787 trades × $0.30 friction) → **fails B3** |
| entry-3.0 | +$2,688 −$158 +$1,849 = **+$4,379** | ≈ −$3,000 (26,919 trades — friction dominates) |

Both reproduce the docs exactly. The signal has a **real gross OOS edge (+$2,554,
66–69% win)**; flat ~$0.30–0.40/trade taker friction erases it. The whole Phase-2
question is whether *any* universe/parameter change lifts net above the bar. §4 answers
it empirically.

### 2.3 The gap between what's been run and what a go-live decision needs

| Requirement for a taker go-live | Covered by the 69 runs? |
|---|---|
| OOS net ≥ +$424 at real taker cost | **No** — best is +$187 |
| Multiple-testing correction across the 69-config search | **No** — no DSR/PBO applied |
| Per-market real spread cost (not flat 0.05%) | **No** — cost is a single flat % for all markets |
| Market-impact charge at real manual size | **No** — all costs assume $100/leg top-of-book |
| Pair-selection stability across spans | **No** — never measured |

These five gaps *are* the sub-phase B backlog (§7). Note three of them make current
results **optimistic**, not pessimistic — so the true picture is at best as good as, and
probably worse than, the +$187 coin flip.

---

## 3. The two liquidity code paths, untangled

There are two independent liquidity mechanisms. **They do not move together**, and the
operator's hypothesis conflates them.

### Path (a) — LIVE / MANUAL SCAN filter: `MIN_LIQUIDITY_USD`
- Default **$10,000** 24h notional (`backend/config.py:188`; `.env.example:33`).
- Applied inside the exchange market-listing call:
  `backend/exchanges/hyperliquid/client.py:249` (`if volume < config.MIN_LIQUIDITY_USD: continue`),
  mirrored in `dydx/client.py:130`.
- **This is the only path the operator's "$10k / ~1900 markets" refers to.** It governs
  the live cointegration scan / manual pair discovery. It has **no effect on any backtest.**

### Path (b) — BACKTEST universe: `_universe()`
- `backend/backtest/engine.py:604-606`:
  ```python
  async def _universe(exchange: str) -> list[str]:
      source = make_candle_source(exchange=exchange)
      return await source.available_markets()
  ```
- The candle source is **a different class from the scan client** —
  `OhlcvCacheSource.available_markets()` (`backend/replay/candle_source.py:56-61`) →
  `get_ohlcv_cache_repository().get_markets(exchange, resolution)`, a bare
  `GROUP BY market` over `ohlcv_cache` (`backend/ingest/cache_repository.py`).
- **There is no liquidity/volume filter and no allow-list anywhere on this path.** The
  backtest universe is simply *every market seeded in the OHLCV cache* (178 HL markets).
- Confirmed at the API layer: `StrategyBody`/`StrategyUpdateBody`
  (`backend/routers/backtest.py:51-93`), the `Strategy` schema, and `engine.run` /
  `_sweep` expose **no** market-subset or threshold parameter. `max_active_pairs` is a
  concurrency cap, not a universe filter.

**Consequence:** raising `MIN_LIQUIDITY_USD` (path a) changes what the *live scan* shows
but does **nothing** to the backtest; adding a liquidity filter to the backtest (path b)
is the "deciding experiment" and **requires an engine code change**. A change to one does
not move the other. Every recommendation below states which path it targets.

> **Open data point to confirm with the operator:** the docs record **176 HL perps after
> the $10k filter** (QA.md:88), but the operator describes the scan passing **~1900**. The
> most likely reconciliation is *markets* (≈176) vs *candidate pairs* (176 markets →
> ~15k possible pairs; ~1900 = survivors of the cointegration/half-life/p-value gates).
> If instead 1900 is a *market* count, the cache/scan universe differs from the docs and
> should be re-audited before any path-(a) change.

---

## 4. Targeted probes (the deciding experiment), with real numbers

**Method.** Rather than create temporary strategy rows (which would need an engine change
to restrict the universe, forbidden in sub-phase A), the probe **re-buckets the
already-computed OOS trades** by a per-market liquidity/volatility proxy. This is
**strictly read-only** — zero writes to prod, nothing to clean up — and directly answers
the crux: *is the OOS gross edge concentrated in markets a liquidity/vol filter would
remove?* Proxy = per-market **median hourly dollar-volume** (`close×volume` over
2025-03-24→2026-03-01) from `ohlcv_cache`. Gross follows the docs convention
(`gross_pnl + funding_pnl`, from the zero-cost runs, i.e. true mid-price gross).

**Limitation (stated honestly):** re-bucketing measures *pruning* existing trades to the
liquid subset. It cannot capture *new* pairs a genuinely narrower cointegration universe
might form among liquid names, nor time-varying liquidity (a single union-window proxy).
That second-order effect is exactly what the engine-change experiment in §7/Slice 2 would
test. But the first-order result is so one-directional that it is decisive for planning.

### 4.1 Liquidity probe — gross collapses as the floor rises

**Entry |Z|≥3.5, OOS s2–s4** (full = 7,787 trades / +$2,554 gross):

| Both-legs floor (median $/hr) | Trades | Gross | Net @ real taker* |
|---|---|---|---|
| none (full universe) | 7,787 | **+$2,554** | +$187 (inside noise floor) |
| ≥ $50k | 3,328 | **−$292** | ≈ −$1,000 |
| ≥ $100k | 2,417 | −$183 | ≈ −$700 |
| ≥ $250k | 1,277 | −$221 | ≈ −$500 |
| ≥ $1M | 823 | +$44 | ≈ −$130 |
| ≥ $5M | 218 | +$98 | ≈ +$54 (218 trades — statistically zero) |

\* Net uses the *best-case* top-quartile slippage for the liquid tiers (0.0086%,
friction ≈$0.21/trade) — i.e. these nets are **generous** and still negative.

**Entry |Z|≥3.0, OOS s2–s4** (full = 26,919 trades / +$4,379 gross): same shape —
+$968 (≥$50k) / +$709 (≥$100k) / +$258 (≥$1M) gross, all deeply net-negative once the
5-figure trade count pays real per-trade friction.

**Reading:** the gross edge lives in the **bottom ~third by liquidity**. Even a mild floor
($50k/hr median ≈ $1.2M/day, ~120× the current scan floor) flips gross negative. The
2026-07-22 projection (+$898/+$654 "if slippage dropped") assumed **constant gross** —
this probe shows gross does *not* stay constant; it collapses. **The operator's hypothesis
is refuted: a higher liquidity floor removes the (illiquid-driven) gross faster than it
saves on cost. It does not create edge.**

### 4.2 Volatility probe — the same trap

**Entry |Z|≥3.5, OOS s2–s4**, per-market realized hourly-return vol (tiers at market
p25/p50/p75 = 0.0105 / 0.0124 / 0.0150):

| Filter | Trades | Gross | Read |
|---|---|---|---|
| full | 7,787 | +$2,554 | — |
| both legs **calm** (≤ p25 vol) | 521 | +$279 | net ≈ +$168 → **noise floor, tiny sample** |
| both legs ≤ median vol | 2,152 | −$164 | negative |
| both legs **hot** (≥ p75 vol) | 338 | +$423 | mid-price mirage on wide-spread names |

The gross that survives is either a **noise-floor calm sliver** or a **hot-market
sliver** whose +$423 mid-price gross sits on exactly the coins with 0.1–0.28% half-spreads
(HMSTR/BOME/PURR-class) — which a taker *pays*. A volatility filter does not rescue net
either.

### 4.3 First-order market-impact estimate (gate B5)

All costs above assume **$100/leg at top-of-book**. Manual size is 10–100× that. A
first-order square-root impact model `impact ≈ σ·√(Q/ADV)` in a *thin* market where the
gross lives (median $30k/hr → ADV ≈ $0.7M/day, daily σ ≈ 5%):

| Per-leg size Q | Q/ADV | Impact/leg | vs 0.0316% measured |
|---|---|---|---|
| $1,000 | 0.0014 | ≈ **0.22%** | ~7× |
| $5,000 | 0.0069 | ≈ **0.49%** | ~15× |

At 0.2–0.5%/leg, friction is **$1.8–$4/round-trip** — several times the entire modelled
cost and **many times** the ~$0.33/trade the strategy earns gross. **The illiquid gross
is structurally unharvestable at real manual size.** This is the single most important
unmodelled risk, and it points the *opposite* way from "trade thinner names for more
dislocation."

---

## 5. Liquidity / volatility recommendation (per code path)

Two independent reasons could motivate raising the liquidity floor. They must not be
conflated:
- **(i) Alpha** — "raise it to make more money." **Refuted** by §4: liquidity is not an
  edge lever here; the gross lives in thin names.
- **(ii) Tractability + executability** — "raise it so the manual scan surfaces a
  reviewable number of names I can actually fill." **Valid and recommended** — this is
  what the filter is *for*.

| Lever | Path | Recommendation |
|---|---|---|
| `MIN_LIQUIDITY_USD` raise | (a) live scan | **Raise it for tractability/executability (reason ii), not for edge (reason i).** The current **$10k floor is effectively inert** — 179/179 cached HL markets already clear it, so it thins nothing. Because the scan pairs markets, the candidate-pair count scales ≈ N²/2, so cutting markets shrinks the manual review list super-linearly. Recommended floor ≈ **$1M/day** (→48 markets, ~1,130 candidate pairs vs ~15,900 today). Trade-off is only that you get fewer signals overall — but the ones you drop are in names you can't fill at size, so no *tradeable* P&L is lost. It *worsens backtest-measured gross*, but that gross is untradeable microstructure — **not a reason to keep the filter loose.** One-line `.env` change, independent of sub-phase B. |
| Backtest universe liquidity/spread filter | (b) `_universe()` | **Do not build it to gain edge — the answer is already "it loses money."** If built (Slice 2), build it to make the backtest **honest** (charge per-market real spreads and optionally exclude untradeable dust), default **OFF**, with this probe's result documented so no one expects alpha from it. |

**Survivor counts by 24h dollar-volume floor** (recent HL, from `ohlcv_cache`):

| Floor (24h $) | $10k (now) | $100k | $1M | $5M | $20M |
|---|---|---|---|---|---|
| Markets | 179/179 | 135 | 48 | 17 | 6 |
| ≈ candidate pairs | ~15,900 | ~9,000 | ~1,130 | ~140 | ~15 |
| Volatility filter | (b) | Same verdict — no edge; only useful as an honesty/robustness lens. |

The productive reframing: **the problem is not "too much noise in the universe," it is
"the gross edge is untradeable microstructure."** Effort should go to *measuring cost
honestly per market* and *correcting for the 69-config search*, not to narrowing the
universe.

---

## 6. External tools / skills — adopt vs reject

Skeptical stance: the project has a working custom walk-forward engine; a tool must
concretely de-risk the **taker-only crypto pairs** problem to earn its place.

**Adopt (small, high-leverage):**
- **Deflated Sharpe Ratio + PBO** (Bailey & López de Prado). This is the highest-value
  addition. 69 configs were searched; the "best" is plausibly the luckiest draw. DSR is a
  ~40-line numpy/scipy function (reference impl: `esvhd/pypbo` for PBO). **What it gives:**
  a defensible, multiplicity-corrected pass/fail for any future candidate (gate B3).
  **Integration cost:** low — a standalone stats module + a dashboard badge. **Build vs
  buy:** build the formula in; do not take a heavyweight dependency.
- **statsmodels** (already a common transitive dep). **What it gives:** reference
  Engle–Granger/ADF/Johansen cointegration + half-life (OLS on Δspread) to *validate* the
  custom engine's math against a trusted implementation. **Cost:** low. Use as a test
  oracle, not a runtime replacement.
- **Stationary bootstrap** (Politis–Romano; `arch` has it). **What it gives:** a proper
  confidence interval on OOS net P&L to formalize the ±$212 noise floor (gate B3) instead
  of a back-of-envelope SE. **Cost:** low.

**Reject:**
- **vectorbt / backtesting.py / zipline / QuantConnect-Lean** — full backtest platforms.
  The engine already does correct walk-forward with real cost/funding accounting;
  re-platforming is large and solves *none* of the five gaps (all are cost/statistics, not
  engine). Reject.
- **ccxt** — the exchange clients already cover HL. Reject.
- **mlfinlab** — has DSR/PBO but is heavyweight and licensing-encumbered; take the DSR
  *formula*, not the library. Reject as a dependency.

---

## 7. The concrete path to a possible "yes" (and the sub-phase B plan)

Because the verdict is **no go-live**, sub-phase B is **not** "ship a strategy." It is
"build the honest measurement + selection machinery so that *if* a real edge exists it can
be proven, and *if* it doesn't (likely) that is settled cheaply." Each slice is a vertical
increment with TDD + a local-dev-docker e2e test, following `.claude/CLAUDE.md` exactly.

**What would have to become true for a "yes"** (the path, stated up front):
1. A config posts OOS net **≥ +$424** at **real per-market taker cost** across a majority
   of s2–s4, **and**
2. survives a **DSR/PBO** correction for the 69-config (and any new) search, **and**
3. keeps a positive net after a **market-impact charge at the operator's real size**.
   The probes make (1) and (3) look unlikely on the *current* signal — so a genuine "yes"
   probably needs a **new signal source** (e.g. funding-carry-aware pair selection, or a
   fundamentally different universe), not another parameter tweak. Slices 1–4 are what let
   us find out honestly.

### Slice 0 — Raise `MIN_LIQUIDITY_USD` (standalone, config-only, path a)
Not really a "slice" — a **one-line config change with no code or engine impact**, listed
here so it isn't lost. It raises the *live/manual scan* floor to bring the hand-review list
to a tractable, fillable size (reason ii in §5). It does **not** touch any backtest, any
trading logic, or `ENVIRONMENT`.
- **Recommended value: `MIN_LIQUIDITY_USD=1000000` ($1M/day)** → ≈48 markets / ~1,130
  candidate pairs (vs 179 / ~15,900 today). Use **$5M** (`5000000`) if you want an even
  tighter shortlist (~17 markets / ~140 pairs); **$100k is too low to matter** (135 markets).
- **Apply:** set it in the prod `.env` and restart the api container
  (`docker compose up -d` — no `--build` needed for an env-only change), *or* bump the
  tracked `.env.example` default + docs and deploy. `.env` stays gitignored per
  `.claude/CLAUDE.md`; only `.env.example` is tracked.
- **Recommended value & timing (expert call, 2026-07-24):** use **$1M**, not $5M — $5M
  (~17 markets) risks starving pair discovery; start looser and tighten empirically only if
  the list stays unwieldy or fills disappoint. **Decide the number now, but do NOT apply it
  to prod during sub-phase A** — it doesn't advance the go/no-go objective (it's the live
  scan, path a; the evidence lives entirely on backtest path b), there's no urgency at a
  no-go verdict, and an env change + restart is a prod mutation (restart also flips
  `SCAN_DATA_SOURCE`→dydx, per §7 gotchas). **Apply it as the first action of sub-phase B**,
  bundled with the `.env.example` + docs sync so tracked config and prod agree (no drift).
  The operator may flip the prod `.env` var by hand at any time for immediate scan-review
  relief, but should still pair it with the tracked-config update.
- **Gate:** operator's call on the exact number; low-risk (config-only, live scan only, no
  effect on saved backtests or on going live).
- **Docs:** `TRADING_CONCEPTS.md` + `USER_GUIDE.md` (update the "$10k" references),
  `.env.example`, `QA.md` (one line: "why did the scan list shrink?").

### Slice 1 — Per-market realistic cost model
Replace the single flat `slippage_pct` with a **per-market spread cost** (seed the measured
per-coin half-spread table; fall back to a volume→spread curve). Re-run s2–s4 at true cost.
- **TDD:** unit tests on the cost function (known coin → known half-spread; fallback curve).
- **e2e (local docker):** a fake-mode backtest whose per-market spreads produce a
  deterministic, asserted net.
- **Docs:** `strategy.md` (new campaign entry), `QA.md` (new Q&A), `BACKTEST_PARAMETER_GUIDE.md`.

### Slice 2 — Liquidity/spread filter on `_universe()` (path b)
Add an **optional, default-OFF** universe filter (dollar-volume floor and/or half-spread
ceiling) to `_universe()` / `get_markets()`, driven by config. Ship it *with this probe's
refutation documented* so it is understood as an honesty/robustness knob, not an alpha lever.
- **TDD:** `get_markets(min_dollar_volume=…)` filters as specified.
- **e2e:** backtest with filter ON vs OFF yields the asserted (smaller) universe + net.
- **Docs:** `BACKTEST_PARAMETER_GUIDE.md`, `QA.md` ("does raising the liquidity filter gain
  edge?" → No, with §4 numbers), `strategy.md`.

### Slice 3 — First-order market-impact charge (gate B5)
Add a size-aware impact term (`σ·√(Q/ADV)` or a calibrated participation model) to the cost
layer, parameterized by per-leg size.
- **TDD:** impact monotonic in size, matches hand-computed values.
- **e2e:** a backtest at $100 vs $5k/leg shows the asserted net divergence.
- **Docs:** `strategy.md`, `TRADING_CONCEPTS.md` (introduce "market impact"), `QA.md`.

### Slice 4 — Multiple-testing correction + defensible selection (gate B3)
Add a DSR/PBO stats module and surface it on the strategy dashboard (a "corrected
significance" badge), so no future config is recommended on an uncorrected leaderboard.
- **TDD:** DSR matches the reference formula on canned inputs; PBO on a synthetic
  overfit set returns ~1.
- **e2e:** dashboard renders the badge for a seeded run.
- **Docs:** `strategy.md`, `QA.md`; touches `ui/lib/strategyTaxonomy.ts` / a new stats module.
- **CONTEXT.md:** update only if this introduces new domain vocabulary
  ("deflated Sharpe", "market impact", "per-market spread") — expected minor.

### Slice 5 (optional) — Pair-selection stability report
Measure how much the selected pair set turns over across s2–s4 (a stable edge should reuse
pairs). Read-only analytics; no trading change.

### Slice 6 — UI + data model: phase tagging & filtering (non-destructive)
**Requirement (operator):** never delete phase-1 strategies, and give the UI a reliable
way to tell phase-2 runs from phase-1. The 69 phase-1 rows are preserved as the honest
baseline; this slice is purely **additive**.

- **Data model:** add **`phase Int @default(1)`** to the `Strategy` model
  (`schema.prisma`). Existing rows auto-backfill to `1`; the sub-phase-B create path
  (and `seed-defaults`) stamp new runs as `2`. A name-prefix convention is explicitly
  **rejected** — the taxonomy already documents that names are unreliable (24 rows are
  "Untitled strategy"; safety is derived from config, not names). The phase tag is an
  orthogonal **provenance** axis that coexists with the existing cost/span/family axes.
  (Phase-2 runs also carry the honest cost model from Slices 1/3, so `phase=2` is
  technically meaningful, not just a label.)
- **API:** `StrategyBody`/`StrategyUpdateBody` gain an optional `phase` (default 1);
  `create_strategy` stamps it. Read endpoints return it. No existing field changes.
- **UI:** extend the PR #217 machinery in `ui/lib/strategyTaxonomy.ts` and the strategy
  list — (1) a **"Phase 2" badge** beside the existing cost-tier and span badges;
  (2) a **Phase filter toggle** (Phase 1 / Phase 2 / All) mirroring the "realistic runs
  only" toggle — **default = All phases** (operator decision 2026-07-24: show everything,
  Phase 1 is never hidden; badge + toggle do the disambiguation); (3) optional top-level
  grouping by phase, families within. Phase-1 view is unchanged.
- **TDD:** classifier unit test (`phase=2` → badge; toggle predicate filters correctly);
  API test (create stamps phase; default is 1).
- **e2e (local docker):** seed one phase-1 and one phase-2 row → assert the badge renders
  and the Phase toggle shows/hides each. Reuses the deterministic per-test demo-state reset.
- **Migration safety:** additive column, default-backfilled — **no row is deleted or
  mutated**. On prod, the documented flow: `pg_dump` → `prisma migrate deploy`.
- **Docs:** `QA.md` ("how do I tell phase-2 strategies from phase-1?"), `USER_GUIDE.md`
  (the new badge + toggle), `strategy.md`.

### Gate & sequencing (per `.claude/CLAUDE.md`)
- Each slice: short-lived `feat-<slug>`/`fix-<slug>` branch **off `main`** → implement →
  **e2e on the local dev docker stack** (`docker compose up -d --build`; remember
  `SCAN_DATA_SOURCE` resets to `dydx` on restart — set back to `hyperliquid` via
  `POST /api/system/data-source` before any HL run; backend tests aren't in the api image —
  `docker cp backend/tests <cid>:/app/tests`) → PR (CI: pytest + typecheck+build + e2e must
  pass) → **explicit operator approval** → merge to `main`.
- Promotion `main → production` and any server deploy is a **separate, explicit operator
  decision**. A deploy must leave the bot **safe** (`ENVIRONMENT` stays testnet); going
  live on mainnet is deliberate, never a deploy side effect. **Nothing here proposes going
  live** — the verdict is no-go until the bar is cleared.
- This plan document itself is committed on a `feat-phase2-plan` branch off `main` once
  approved (it must not land directly on `production`).

---

## 8. Video (operator decision 3)
`youtube.com/watch?v=KBQ6Z9A5IE4` could **not** be retrieved: WebFetch returns only
YouTube navigation chrome, and the video ID does not surface in web search. Per operator
decision 3 this is best-effort — noted and skipped; **nothing adopted or discarded from
it.** If the operator considers it pivotal, a pasted transcript/summary can be folded into
§6 before sub-phase B starts.

---

## 9. Quant review — reliability/profitability gaps a taker-only operator must care about

1. **Multiple testing / overfitting.** 69 configs, best selected by net P&L on a lucky
   in-sample window. Without DSR/PBO the "best" is likely the luckiest draw. The Phase-1
   taxonomy already de-fangs the leaderboard (families, cost/span badges, realistic
   toggle); Slice 4 formalizes it into a pass/fail. **This is the biggest statistical gap.**
2. **OOS discipline.** Good foundation (s1–s4 defined). Make OOS the *only* admissible
   evidence (B1) and never rank by in-sample net again.
3. **Cost realism.** Mid-price gross materially overstates tradeable P&L; the real
   opponent is the per-market **spread + impact**, which §4–§5 show is *concentrated in
   exactly the markets that generate the gross*. A single flat 0.05% understates the true,
   market-dependent cost (Slices 1 & 3).
4. **Universe construction.** No backtest liquidity filter is *fine for measuring gross*
   but means the gross is inflated by untradeable thin names. The fix is honest per-market
   costing, **not** narrowing the universe (which the probe shows loses money).
5. **Pair-selection stability.** Unmeasured. A real edge should reuse pairs across spans;
   high turnover would be another overfitting tell (Slice 5).
6. **Defensible selection criterion.** = **OOS-only, real-per-market-cost, size-aware,
   DSR-corrected, cross-span-robust.** That is the bar in §1, and building the machinery to
   *evaluate* candidates against it is what sub-phase B delivers.

**Bottom line:** the dashboard faithfully answers "what did this run produce?"; the bar in
§1 answers "would this make money going forward?" On today's evidence, honestly measured,
the answer is **no** — and neither a liquidity nor a volatility filter changes it.
```
