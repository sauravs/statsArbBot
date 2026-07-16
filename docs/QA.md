# Feature Q&A Log

Running log of `/feature-qa` questions and answers.

> **Version-controlled.** This file is tracked in git and promoted to `production` with the
> rest of the repo. Newest entries appended at the bottom.

---

## 2026-06-11 — Normalized price (rebased to 100): what & why

**Q:** related to charting category, what is Normalized price (rebased to 100), what is its importance, why we are using it?

**A:** Each leg's raw price series is rescaled so its **first bar in the chart window equals 100**, then every later point is relative to that: `value = price / price[0] * 100`, applied independently to each leg (`backend/marketdata/pair_series.py:381-386`). A reading of 112 = up 12% since the window start; 95 = down 5%. It feeds **Panel 1** of the pair-detail chart (base green / quote blue) in `ui/components/PairCharts.tsx:259`.

**Importance / why we use it:** the two legs trade at very different absolute prices (e.g. BTC ~$60k vs SOL ~$150). Plotting raw prices on one axis makes the cheap leg a flat line and the expensive one dominate — you can't visually compare their movement. Rebasing both to 100 puts them on the same percentage scale, so you can:
1. See them co-move and then diverge on a like-for-like basis (`docs/USER_GUIDE.md:104`).
2. Get the visual intuition behind the pairs trade — divergence now, expected re-convergence (the human-readable version of the Spread/Z-score math).
3. Sanity-check a signal before acting: is the spread genuinely mean-reverting, or is cointegration breaking down? (`docs/USER_GUIDE.md:108`).

**Key caveat:** the normalized overlay is **purely visual/diagnostic** — it does NOT generate signals. Trade logic runs off the **Spread** (`S1 − β·S2 − α`) and **Z-score** (Panel 3, "the chart you trade off", `docs/USER_GUIDE.md:106`). The rebased-to-100 panel just makes the relationship legible to a human.

---

## 2026-06-11 — Quick vs Full scan, signal direction (BUY/SELL base), Z-threshold slider

**Q:** related to manual trading section, how quick and full scan different to each other, what is its purpose, how and why BUY base SELL quote or vice versa signal got generated, purpose of Z threshold slider. Please explain with analogies and examples.

**A:**

**Quick vs Full scan** — same job (sweep dYdX perp pairs, Engle-Granger cointegration test, fit β/α, compute spread + half-life, keep pairs with `p < 0.05` and `half-life ≤ 72h`); the only difference is history depth:
- **Quick scan** = `SCAN_QUICK_PAGES = 2` ≈ 200h ≈ **8 days** — fast, rough look.
- **Full scan** = `NUM_HISTORICAL_PAGES = 4` ≈ 400h ≈ **16–17 days** — slower, the trustworthy result; persists in the DB (survives reload).
- Sources: `backend/config.py:130-133`, `backend/routers/scan.py:24-33`, `docs/USER_GUIDE.md:75-76`.
- Analogy: Quick = Google Maps' instant route estimate; Full = the route after it pulls live traffic — the one you actually drive. A pair cointegrated over 8 days may fall apart over 16; Full is what you trust before risking money.

**Signal direction (`Z<0` → BUY base/SELL quote; `Z>0` → SELL base/BUY quote)** — `docs/USER_GUIDE.md:26`. Z measures how far the spread `S1 − β·S2 − α` is from its mean in σ; the trade always bets the spread reverts:
- `Z < 0` = spread abnormally low = base **cheap** vs quote → buy base, sell quote.
- `Z > 0` = spread abnormally high = base **expensive** vs quote → sell base, buy quote.
- Market-neutral: you bet on the *relationship* snapping back, not either coin's absolute direction (quote leg scaled by β so the two legs cancel market moves).
- Analogy: two dogs on a leash (cointegrated). When one sprints ahead (spread stretches), bet the leash pulls them back. `Z<0` = base dog lagged → back base / fade quote. `Z>0` = base dog ran ahead → fade base / back quote.
- Direction is **inferred automatically from the entry z-score** — same rule the bot uses (`docs/USER_GUIDE.md:121`).

**Z-threshold slider** (range 0.5–4.0, default 1.5; `docs/USER_GUIDE.md:94-96`) — your sensitivity dial for what counts as a signal. A pair goes "active" (shows BUY/SELL Signal + Record button) only when `|Z| ≥ threshold`. Lower it → more, weaker signals; raise it → fewer, higher-conviction ones. Re-filters the table live.
- Analogy: the sensitivity knob on a metal detector — high = only big targets (few false alarms, may miss small finds); low = beeps at every bottle cap (see everything, mostly noise). 1.5 is the research-backed "Option-B" sweet spot.
- Caveat: the slider sets *your view's* entry threshold; the bot's enforced **stop-loss `|Z| ≥ 4.0`** and **take-profit `|Z| < 0.5`** stay fixed regardless (`docs/USER_GUIDE.md:27-28`).

---

## 2026-06-11 — "Z thresholds entry/exit/stop [Edit]" control: what it changes & where

**Q:** related to manual trading section, what is this value "Z thresholds entry ±1.5 · exit ±0.5 · stop ±4 (edit)" button, how is it affecting other parts of this manual trading section? What happens when we edit these values and where exactly do its effects take place?

**A:**

**What it is:** the `StrategyThresholdsControl` badge + Edit button (`ui/components/StrategyThresholdsControl.tsx`). Edits the **Option-B entry/exit/stop Z thresholds app-wide at runtime** (issue #74). It is **distinct** from the dashboard's "Active when |Z|" **slider**, which is a separate client-only filter (`ZThresholdSlider.tsx:3-5`; noted at `StrategyThresholdsControl.tsx:6-8`).

**Edit → Apply flow:**
1. Client guard rejects anything not `exit < entry < stop` (`StrategyThresholdsControl.tsx:51`).
2. POST `api/system/thresholds` (`ui/lib/api.ts:74-79`) → `backend/routers/system.py:109`.
3. Backend re-validates (422 on violation), then `config.set_signal_thresholds()` mutates live globals `ZSCORE_THRESH/EXIT_ZSCORE/STOP_LOSS_ZSCORE` (`config.py:97-98`). Consumers read at call time → **immediate, no restart** (`system.py:114-116`).
4. Persists to `BotConfigHistory` so it survives restart (`system.py:127`); DB hiccup keeps the runtime value and returns `persisted:false` without error (`system.py:134-139`).

**Where effects land (read config at call time):**
- **Pair-detail Z chart** — `/api/pairs/.../series` builds reference lines + entry/exit markers from `config.ZSCORE_THRESH/EXIT_ZSCORE/STOP_LOSS_ZSCORE` (`pair_series.py:407-409`, markers `:283-294`). Lines/markers redraw on next chart load.
- **Live bot + sims (real-time, fast-forward)** — same globals as default signal rules.
- **statcore signal eval** — `evaluate_entry`/exit (`pair_series.py:309-321`).

**Effect on the Manual Trading section specifically:**
- ✅ Changes the **pair-detail Z chart** you study before recording (lines + markers) — the only visible manual-section effect.
- ❌ Does **not** change which pairs are active/recordable — that's the separate "Active when |Z|" slider.
- ❌ Does **not** alter already-recorded trades — `backend/routers/manual.py` doesn't read these thresholds; a recorded trade captures β/half-life/current-Z/spread/entry prices, direction inferred from Z sign.
- ❌ Does **not** trigger any automatic action — manual trades have no auto-exit; you "Mark closed" yourself.

**One-liner:** it sets the app-wide strategy entry/exit/stop (live in config, persisted to DB, read by chart + live bot + sims). In the manual section its only effect is cosmetic-on-the-chart; it deliberately does NOT drive the recordable-pairs filter, recorded trades, or any automatic manual-trade action. (Easy-to-conflate UX: the "[Edit]" badge = real strategy thresholds; the slider = view-only table filter.)

---

## 2026-06-14 — Why so many cointegrated pairs on Hyperliquid vs dYdX?

**Q:** why so many cointegrated markets i am able to see in hyperliquid manual section as compared to dydx inspite of that in hyperliquid we have just last 2 month historical record right?

**A:** The premise has a hidden flaw, then three real reasons.

**The scan window is NOT 2 months.** The cointegration scan that fills the manual section uses `NUM_HISTORICAL_PAGES=4 × CANDLES_PER_PAGE=100 ≈ 400 hourly bars ≈ ~16 days` (full scan; `SCAN_QUICK_PAGES=2 ≈ ~8 days` quick) — `backend/scan/orchestrator.py:139`, `config.py:153-155`. The **60-day window in the Data tab is the *backtest* cache, not the scan window**; both dYdX and HL scans run over the same ~2-week window. The HL scan covered **176 markets → ~15,400 candidate pairs, 1,986 passed `p<0.05`** (`PVALUE_MAX`, `config.py:101`; filter at `orchestrator.py:71,90`).

Three reasons HL shows so many:
1. **Quadratic in universe size.** Pairs ≈ N(N−1)/2. HL lists far more liquid perps (176 here, after the `MIN_LIQUIDITY_USD=10k` filter, `config.py:182`) than dYdX, so even at the same survival rate it yields many more. (Dev DB currently has **no real dYdX scan** — `/api/pairs?exchange=dydx` → 0 — so run a dYdX scan to compare apples-to-apples.)
2. **Less history → MORE spurious cointegration, not fewer.** Counter-intuitive: over a short sample the Engle–Granger/ADF test has low power + high false-positive rate, so more pairs pass `p<0.05` by chance. *More* history is a *stricter* filter. So a short window inflates the count.
3. **Alt/meme-heavy universe.** HL's `kPEPE`/`kSHIB`/`2Z`/`0G`/`ASTER` carry high BTC/ETH beta and co-move → manufactured cointegration.

**Takeaway:** 1,986 is mostly noise; the high count warrants *more* skepticism. Filter hard on low p-value AND short half-life, and re-validate a candidate on the 60-day HL backtest (out-of-sample) before trusting it.

---

## 2026-07-15 — Outcome & Reason columns: how a row is computed from raw candles; all Reason/Outcome types

**Q:** Follow-up on the Outcome/Reason columns. Take the two highlighted blotter rows as examples and explain how those numbers are calculated from the raw price CSV data. How many different Reason types are there and on what criteria? Same for Outcome.

**A:** The two highlighted rows (strategy "Untitled rank #1": Entry |Z|≥3, Exit |Z|<0.5, Stop |Z|≥4, Z-window 21, $100/trade):

| Pair | Dir | Entry (z · base/quote px) | Exit (z · base/quote px) | Hold | Net P&L | Outcome | Reason |
|---|---|---|---|---|---|---|---|
| ACE/TRX | L/S | z=−3.32 · 0.109 / 0.3218 | z=0.06 · 0.1107 / 0.3219 | 11h | **+$0.94** | ✓ Win | Reverted |
| AXS/GMX | L/S | z=−3.06 · 1.074 / 5.957 | z=−0.46 · 1.0721 / 5.8516 | 11h | **−$0.01** | ✗ Loss | Reverted |

**From raw candles to the row (pipeline):**
1. **Raw data** = hourly OHLCV candles per market (the "2,975,904 bars" cache). Everything below is derived from the two legs' `close` prices.
2. **Formation window** (scan): regress base on quote → **hedge ratio β + intercept α** (the cointegration fit), persisted on the trade (`BacktestTrade.hedge_ratio/intercept`, `schema.prisma:515`).
3. **Trade window**: each bar, `spread = base − β·quote − α`; rolling mean/std over the 21-bar Z-window → **z-score** (`backend/statcore`, `docs/TRADING_CONCEPTS.md`).
4. **Entry**: fires when `|z| ≥ 3`; direction from z sign — `z<0 → LONG_BASE` (**L/S** = BUY base, SELL quote). Both rows entered at z≈−3.x. Sizing: `base_size = $100 / base_px`, `quote_size = base_size × |β|` (`simulate_pair_entry`, `costs.py:104-122`). Each leg fills at the bar close ± **0.05% slippage** (`apply_slippage`, `costs.py:49-52`).
5. **Exit**: each later bar re-checks the rules; both closed when `|z| < 0.5` (ACE/TRX z=0.06, AXS/GMX z=−0.46) → reason **TAKE_PROFIT** ("Reverted").
6. **P&L on close** (`compute_exit_pnl`, `costs.py:125-168`): per leg `leg_pnl = side_sign·(exit−entry)·size` (`statcore/pnl.py:36-38`); `gross = base_leg + quote_leg`; `fee_cost` = taker fee (0.05%) on all four fills; `funding_pnl` accrues hourly (long pays / short receives); **`net_pnl = gross − fee_cost + funding_pnl`**. That `net_pnl` is the Net P&L column.

**Why one Wins and one Loses (same Reason):**
- **ACE/TRX** — long ACE rose 0.109→0.1107 (**+1.6%** ≈ +$1.5 on the ~$100 base leg) while short TRX was flat (0.3218→0.3219). The legs **diverged favourably** → gross ≈ +$1.5, minus ~$0.2 round-trip fees ± small funding → **+$0.94, Win**.
- **AXS/GMX** — long AXS *fell* 1.074→1.0721 (−0.18%, the long leg *loses* ~$0.18) but short GMX also fell 5.957→5.8516 (−1.8%, the short *gains*, scaled by β). Both legs **co-moved down**, so the market-neutral pair captured almost no dollar edge → gross ≈ $0; fees net of funding tipped it to **−$0.01, Loss**.

So both are **"Reverted"** because the *z-score* snapped back from ≈−3 to inside ±0.5 (the thesis worked in z-space) — but the dollar result depends on how much the two legs actually *diverged in price*, which is a separate thing. (Exact gross/fees/funding for any row is now on the **Chart ↗** page's cost-breakdown line.)

**Reason — 5 possible values in a backtest** (the exit *trigger*, decided in `backend/statcore/signals.py:99-151` `evaluate_exit`, precedence order; display labels from `ui/lib/exitReason.ts`):
1. `STOP_LOSS_ZSCORE` → **"Z-stop"** — `|z| ≥ stop` (4.0); checked first (breakdown, cut the loss).
2. `TAKE_PROFIT` → **"Reverted"** — `|z| < exit` (0.5); the spread reverted.
3. `STOP_LOSS_TIME` → **"Time-stop"** — `age > 3 × half_life` without reverting.
4. `END_OF_WINDOW` → **"Window end"** — any position still open at the last bar of the trade window is force-closed (`engine.py:539,570`).
5. `STOPPED` → **"Stopped"** — the run was manually stopped mid-position.
(Live trading adds `RECONCILED`/`ORPHANED`/`ABORTED`/`CANCELLED` from `backend/trading/`, but those never appear in a backtest.) None of these depends on P&L.

**Outcome — driven purely by the sign of `net_pnl`** (`ui/components/StrategyDetail.tsx`, blotter row): `net_pnl > 0` → **✓ Win**; `net_pnl < 0` → **✗ Loss**; `net_pnl == 0` → **Flat**. Note it uses the *true* 6-dp `net_pnl`, not the 2-dp display — so a row can read **$0.00** yet show **✓ Win** (e.g. AXS/SKY: a tiny positive that rounds to $0.00 in the column but is `>0`). Reason and Outcome are orthogonal: Reason = *why it closed* (z/time rule), Outcome = *did it make money* (dollar sign).

---

## 2026-07-16 — What fees & funding values does the backtest actually deduct?

**Q:** Related to the Backtest / Walk-Forward Windows expanded trade columns — the "Reason" tooltip says "…a Reverted exit can still be a net loss after fees & funding." What are the fees and funding values we're deducting?

**A:** All three frictions live in the cost model `backend/simulation/costs.py` and are **per-strategy fields** (defaults below; settable via the create/update API — `StrategyBody`, `routers/backtest.py:69-71`; schema defaults `prisma/schema.prisma:450-452`). `net_pnl = gross − fee_cost + funding_pnl` (`costs.py:161`).

- **Taker fee — default `taker_fee_pct = 0.05%`, charged per leg on every fill.** A round trip = entry + exit on both legs = **4 fills**, each `0.05% × that fill's notional` (`_fill_leg`, `costs.py:82-92`; exit fee `costs.py:157-159`). `fee_cost` = entry fees + exit fees. It's **not a fixed dollar amount** — it scales with each leg's notional. On the default `USD_PER_TRADE = $100` base leg (`config.py:112`) that's ~$0.05 per base fill (~$0.10 base round-trip); the quote leg is β-weighted (`quote_size = base_size × |β|`), so its notional — and its fee — varies by pair. A typical round trip is on the order of **$0.15–$0.30** in taker fees.
- **Slippage — default `slippage_pct = 0.05%`, per leg per fill, as an adverse fill price** (BUY fills up, SELL fills down; entry *and* exit) — `apply_slippage`, `costs.py:49-52`. It's not a separate line item: it worsens the fill price, so it silently reduces `gross_pnl` (and nudges the fee base).
- **Funding — NOT a fixed value: the real historical hourly rate per leg.** Accrued every `funding_freq_h = 1` hour at each leg's actual funding rate from `FundingRateCache` (ingested alongside candles; `historical_feed.py:148-166`). A **long leg pays** funding, a **short leg receives** it, each on its notional (`compute_funding`, `costs.py:191-212`): for `LONG_BASE`, `funding = −base_rate·base_notional + quote_rate·quote_notional`. Netted across the two legs and summed over every hour held, `funding_pnl` can be **positive (earn carry) or negative (bleed)**. A missing rate is treated as 0; if a run has no funding data at all, no funding accrues.

**So the "value deducted" isn't one number** — it's `4 × 0.05%` taker fees on the (β-weighted) leg notionals, plus `0.05%` adverse slippage baked into the fills, plus the signed sum of the real hourly funding over the hold. That's why an 11-hour "Reverted" trade whose spread only partly reverted can still land at −$0.01/−$1.47: a small `gross` gets eaten by ~$0.2 of fees + slippage ± funding.

**Two caveats:** (1) These are **defaults** — a strategy can be created with different `slippage_pct` / `taker_fee_pct` / `funding_freq_h` (0–5% / 0–5% / 1–24h). (2) On the **demo/`fake` data source only**, the `END_OF_WINDOW` force-close zeroes slippage & taker fee (`engine.py:570-571`); on real Hyperliquid/dYdX data (what the live backtest uses) the configured percentages apply on every close. The exact per-trade `gross_pnl` / `fee_cost` / `funding_pnl` split for any row is shown on the **Chart ↗** page's cost-breakdown line.

---
