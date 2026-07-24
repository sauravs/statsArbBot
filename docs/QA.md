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

## 2026-07-15 — Why is a *losing* per-trade P&L labelled "TAKE_PROFIT"?

*(logged via `/qa-skill`)*

**Q:** In the Backtest section, for "Untitled strategy rank #1" (Net P&L $1864), the expanded per-entry travelog shows a row like `ARK/ME  S/L  03-23 00:00 · z=3.28 · 0.1643/0.1037  →  03-23 17:00 · z=0.50 · 0.1705/0.1069  17h  -$1.47  TAKE_PROFIT`. Even though this trade's Net P&L is a loss (red, -$1.47), the exit REASON is given as TAKE_PROFIT — shouldn't it say "loss" or something?

**A:** This is **expected**, not a bug. The exit **reason** and the **dollar P&L** are two independent things:

- **The reason describes *which signal rule* closed the trade — it is purely z-score-based, never P&L-based.** The single source of truth is `evaluate_exit()` in `backend/statcore/signals.py:99-151`. It closes a position for exactly one of three reasons, in precedence order: `STOP_LOSS_ZSCORE` (`|z| ≥ 4.0`, `:135`), then `TAKE_PROFIT` (`|z| < exit_threshold`, default 0.5, `:138`), then `STOP_LOSS_TIME` (held > 3 × half-life, `:141`). `TAKE_PROFIT` literally means "the spread reverted back inside the exit band" — i.e. **the mean-reversion thesis played out** (`ExitReason.TAKE_PROFIT` is documented as "|Z| reverted below the exit threshold", `signals.py:50`). In your row that's exactly what happened: entry `z=3.28` → exit `z=0.50`, the gap snapped back. So the engine correctly tags it TAKE_PROFIT.

- **The dollar P&L is computed separately and *nets out costs*.** `net_pnl` is capital-based and already subtracts taker fees, funding, and slippage (`backend/backtest/engine.py:448`, `:570-571`; funding accrued each hour, `:367-371`). So a trade can hit its take-profit *signal* and still be **net-negative in dollars** whenever the captured spread move is smaller than the round-trip cost. That's precisely this trade: it only reverted to `z=0.50` (not all the way to 0), so the spread gain was modest, and 17h of funding + entry/exit taker fees on both legs tipped it to **-$1.47**. `docs/TRADING_CONCEPTS.md:311-316,300-308` calls this out directly — "Finding trades ≠ making money"; naive pairs are often net-negative after fees + funding even when the signal works.

**One-line mental model:** *TAKE_PROFIT = "the spread reverted (the trade thesis succeeded)"; the red −$1.47 = "the reversion wasn't big enough to beat fees + funding."* A losing TAKE_PROFIT row is the normal, honest picture of a small win eaten by costs — not a mislabel. (If you want the label to track dollars instead, that would be a UI/semantics change; today the three reasons are strictly the z-score/time rules from `signals.py`.)

**Re-verified against the actual UI screenshots (2026-07-15, Walk-Forward Backtest, HYPERLIQUID LIVE data, window 0: scan 2026-03-01→03-22, trade 2026-03-22→03-29).** The row is confirmed verbatim: `ARK/ME · S/L · entry z=3.28 → exit z=0.50 · 17h · −$1.47 · TAKE_PROFIT`. This strategy's config badge is **Entry |Z|≥3 · Exit |Z|<0.5 · Stop |Z|≥4** (the `1.5` on the left panel is just the blank "new strategy" form, not this strategy). The screenshots contain a decisive proof that the reason is z/time-based, not P&L-based: two *losing* rows carry *different* reasons — `ARK/ME` (exit z=0.50, 17h, −$1.47) → **TAKE_PROFIT**, whereas `ETC/NIL` (exit **z=1.10**, **30h**, −$9.52) → **STOP_LOSS_TIME**, because z=1.10 is neither < 0.5 (take-profit) nor ≥ 4 (stop-z), and it aged past the time-stop. Other losing-but-`TAKE_PROFIT` rows in the same window corroborate: `0G/IP` (exit z=0.45, −$0.12), `MEME/SUPER` (exit z=0.28, −$0.34). Original answer stands unchanged.

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

## 2026-07-16 — Deriving 0G/MET & 0G/IP; how to read/tune the backtest table; what made rank #1 profitable

**Q:** For the two highlighted backtest trades 0G/MET and 0G/IP (Untitled strategy rank #1, Hyperliquid), how are the table values derived (with actual values and steps)? How should traders approach these backtest table values to analyze and tune input parameters? How did this strategy gain the most profit, what are the likely reasons, and what do you recommend for creating profitable backtest strategies?

**A:** Strategy rank #1: **Entry |Z|≥3 · Exit |Z|<0.5 · Stop |Z|≥4 · Z-window 21 · Scan 21d / Trade 7d · $10k**, 13/13 windows, **9,439 trades, 63% win, Net +$1,864.90** (final $11,864.90 ≈ **+18.6%**). Both highlighted rows are in window 0 (scan 2026-03-01→03-22, trade 2026-03-22→03-29). Both are **S/L** = `SHORT_BASE` (SELL base 0G, BUY quote), entered because entry z>0.

**How the two rows are derived (pipeline + numbers), `USD_PER_TRADE=$100`:**
1. Formation scan regresses 0G on the quote over 21d → hedge ratio β + intercept α (persisted on the trade). Each trade-window bar: `spread = 0G − β·quote − α`; rolling mean/std over 21 bars → z.
2. Entry when `|z| ≥ 3`; z>0 → SHORT_BASE (SELL 0G, BUY quote). `base_size = 100/entry_0G_px`; `quote_size = base_size·|β|`. Fills take the bar close ±0.05% slippage.
3. Exit the first bar `|z| < 0.5` → reason **Reverted** (TAKE_PROFIT). Per-leg P&L `= side_sign·(exit−entry)·size` (`statcore/pnl.py:38`); `gross = base_leg + quote_leg`; `net = gross − fees(0.05%×4 fills) + funding(hourly, long pays/short receives)`.

- **0G/MET · +$1.70 · Win · 5h.** Entry z=3.19, px 0G 0.5285 / MET 0.1414 → exit z=0.45, px 0.5233 / 0.1435. base_size ≈ 100/0.5285 ≈ **189 units 0G (short)**. Short 0G leg: `−(0.5233−0.5285)·189 = +$0.98` (0G **fell** → short wins). Long MET leg: `+(0.1435−0.1414)·quote_size` > 0 (MET **rose** → long wins). **Both legs moved the right way** (spread fell = the SHORT_BASE thesis), 5h hold → tiny funding → clean **+$1.70**.
- **0G/IP · −$0.12 · Loss · 14h.** Entry z=3.09, px 0G 0.5285 / IP 0.6575 → exit z=0.45, px 0.5313 / 0.6657. Short 0G leg: `−(0.5313−0.5285)·189 = −$0.53` (0G **rose** → short **loses**). Long IP leg: `+(0.6657−0.6575)·quote_size` > 0 (IP rose more → long wins ≈ +$0.6). gross ≈ +$0.1; minus ~$0.2 fees and 14h of funding → **−$0.12**.

**The lesson from the pair:** same base (0G short at 0.5285, same 23:00 entry), same reversion target (exit z=0.45), same **Reverted** reason — but **opposite dollar Outcome**. The z-score reverting only guarantees the *reason*; the *dollars* depend on **which leg did the reverting** (0G/MET: 0G fell, the intended way; 0G/IP: 0G rose, so the short leg bled and only the quote leg saved it) and on **hold time** (14h vs 5h → more funding). So Reason = "did the spread revert (z)"; Outcome = "did that reversion put dollars on the board after the legs' real moves + costs."

**How to read the table (in order):** (1) headline — Net P&L, **Win rate**, Trades; (2) **equity-curve shape** — smooth up-and-to-the-right beats a jagged line that ends positive (rank #1's curve grinds up with recoverable drawdowns); (3) **per-window consistency** — is it many green windows or one lucky one? (rank #1: 13/13); (4) **exit-reason mix** — high **Reverted** share = healthy mean-reversion; lots of Z-stop = cointegration breaking down; lots of Window-end/Time-stop = windows too short or pairs too slow; (5) only then drill into the **blotter** for outliers. Don't fixate on any single row (a −$0.12 is noise); the strategy is the *sum* of thousands of trades — what matters is **average win × win-rate > average loss × loss-rate** (`docs/TRADING_CONCEPTS.md` Part 4). Tune **one parameter at a time**, re-run, and prefer results that hold across windows (`docs/BACKTEST_PARAMETER_GUIDE.md`).

**Why rank #1 made the most money (likely reasons):**
1. **High entry bar (|Z|≥3, vs default 1.5).** It only opens on *extreme* dislocations, which revert more reliably → higher win-rate, fewer marginal trades bleeding costs. (Sweep evidence: Entry 1.0 → 49% win, negative; Entry 2.0 → 72% win — `BACKTEST_PARAMETER_GUIDE.md:37-39`.)
2. **Short trade window (7d).** Positions can't linger, so **funding stays small** and the walk-forward **re-scans often** (13 windows) — always trading *currently* cointegrated pairs, not stale ones. The 0G/IP vs 0G/MET contrast shows how a longer hold erodes a thin edge.
3. **Short scan window (21d) on a big universe.** Shorter formation **aligns more markets** → more candidate pairs (`BACKTEST_PARAMETER_GUIDE.md:56-64`), and Hyperliquid lists ~176 perps, so even a thin per-trade edge × **9,439 trades** compounds (small wins like +$1.70/+$2.53 outnumber small losses like −$0.12).
4. **Positive expectancy, well-diversified.** 63% win with average win > average loss, spread across thousands of trades so no single trade can sink it — the compounding shows as a rising equity curve.

**Recommendations for profitable backtests:**
- **Raise Entry |Z| to ~2.5–3** for conviction (fewer, higher-quality trades); keep **Exit 0.5 / Stop 4**.
- **Keep the trade window short (7–15d)** to cap funding and force frequent re-scans; **scan 21–30d** to align more markets without spurious fits.
- **Insist on walk-forward across many windows** and **re-run on a different date span** — a config that only wins in one window is curve-fit (36 strategies were tried here, so the top one is partly a multiple-comparisons artifact until re-validated).
- **Make the average winner clear the round-trip cost** (~0.05%×4 fees + slippage + funding). High entry-Z helps because bigger dislocations → bigger reversions.
- **Judge on curve shape + exit mix**, not just the final number; and **discount for live slippage** — backtests assume clean fills; real Hyperliquid fills are worse (`docs/TRADING_CONCEPTS.md` Part 5).
- ⚠️ Reality check: the parameter-guide sweeps found **naive crypto pairs are usually net-negative after costs** (`BACKTEST_PARAMETER_GUIDE.md:80-83`); rank #1's +18.6% is over one Hyperliquid span and should be treated with suspicion until it survives out-of-sample re-runs and (eventually) testnet.

*(Note: a full data-backed comparison of all 36 saved strategies' exact configs would require reading the production DB, which auto-mode blocked; the above uses rank #1's on-screen config + the empirical sweeps in `BACKTEST_PARAMETER_GUIDE.md`. Happy to pull the per-strategy configs if you approve the prod read.)*

---

## 2026-07-16 — 0G/MET: did it exit too early? P&L re-verification of the trade and of rank #1

**Q:** For 0G/MET (rank #1): at the entry and exit points the price hadn't converged much and yet it exited — it converged a bit further *after* the exit; I think we should have waited more. Analyze this trade's data + chart (and other sample charts if needed), tell me how to improve it, what's lacking in the strategy, how to customize it further, and re-verify/re-evaluate whether rank #1's total Net P&L is correct. Log every calculation.

**A:** **You're right that this specific trade left convergence on the table — but "wait more" is not free, and one continuation is hindsight.** The chart's own panels: entry `2026-03-22 23:00` at **z=3.19** (spread ≈ +0.02), exit `2026-03-23 04:00` at **z=0.45** (spread ≈ +0.01) — the exit fired because `|z| < 0.5` (Reverted). The Spread panel shows the spread kept falling *after* exit, through mean (0.00) down to **−0.04** by ~03-27. So holding longer would have captured more spread.

**How much more (with numbers, position from the chart):** the gross of $2.11 came from the spread moving 0.02→0.01 (≈0.01), and each 0.01 of spread ≈ `Δspread × base_size = 0.01 × 189 ≈ $1.9` gross. To full mean-reversion (spread→0, another 0.01): **+~$1.9 gross**. To the −0.04 trough (another ~0.05 from exit): **+~$9.5 gross**. But the costs of waiting: funding ran **−$0.22 in just 5h** (≈ −$0.044/h), so holding to the 03-27 trough (~96h) ≈ **−$4+ funding**; and the **time-stop (3 × half-life)** would force-close long before then (a ~17h half-life → force-close ~51h in, capturing only part of it). So the *realistic* extra from waiting is a fraction of the $9.5, net of several dollars of funding — and only because *this* trade happened to keep reverting. Just as often the spread stalls or re-diverges right after `|z|<0.5`, where exiting early was correct. **The exit rule can't see the future**, so this is a systematic trade-off, not a per-trade mistake.

**Trade P&L re-verified from the raw prices** (entry 0G $0.52851 / MET $0.14144 → exit $0.52329 / $0.14347, `$100`/trade, SHORT_BASE = short 0G / long MET):
- `base_size = 100 / 0.52851 = 189.211` units 0G.
- SHORT 0G leg: `(0.52851 − 0.52329) × 189.211 = +$0.9877` (0G fell → short wins).
- Implied `quote_size = (2.11 − 0.9877) / (0.14347 − 0.14144) = 552.9` units MET ⇒ **β ≈ 2.92**. LONG MET leg: `(0.14347 − 0.14144) × 552.9 = +$1.1223` (MET rose → long wins).
- **Gross = 0.9877 + 1.1223 = $2.11** ✓ (matches the chart).
- Fees = `0.05% × (100.00 + 78.20 + 99.01 + 79.32 fill notionals) = $0.178` ≈ **−$0.18** ✓.
- Funding = **−$0.22** (net paid over 5h; short 0G receives, long MET pays). Net = `2.11 − 0.178 − 0.22 = $1.71`, stored/displayed **$1.70** ✓. *(Minor UI note: the breakdown line shows each component rounded to cents, so `2.11 − 0.18 − 0.22 = 1.71` vs the displayed Net 1.70 — a $0.01 sum-of-rounded artifact, not an error.)*

**What's lacking / how to customize (tied to real parameters):**
- **Exit |Z| is a single symmetric threshold (0.5) — it takes the *reliable middle* of the reversion and deliberately leaves the tail.** To capture more per winner, **lower `exit_threshold`** (0.5 → 0.2 → 0.1; it's a real per-strategy field, range `>0…2.0`, `routers/backtest.py`). Trade-off: longer holds → more funding, and some trades never reach the tighter target → they exit on the **time-stop / window-end** instead. Net effect must be **backtested**, not assumed.
- **No "ride through the mean" / asymmetric exit.** Exiting only when z crosses to the *opposite* band (e.g. −0.5) would capture overshoots like this one — but that's a **code change**, not a parameter (exit is `|z| < exit_threshold`, `backend/statcore/signals.py:138`), and it holds much longer (funding + breakdown risk).
- **No trailing exit** on z or spread (would let strong reversions run) — also a code enhancement.
- **Z-window (21)** governs how fast z reverts: shorter → exits sooner, longer → holds longer. Tunable (`zscore_window`).
- **Concrete next step:** clone rank #1, sweep **Exit |Z| = 0.5 vs 0.3 vs 0.1**, re-run, and compare Net P&L / win-rate / avg-hold / funding drag. That's the empirical answer to "should we wait more."

**⚠️ Chart caveat (drift):** the Z-score panel's reference lines read **"entry ±1.5 · exit ±0.5 · stop ±4"** — those are the **app-wide live config defaults**, *not* this strategy's actual **Entry ≥3**. The pair-chart draws its threshold lines from `config.ZSCORE_THRESH/EXIT_ZSCORE/STOP_LOSS_ZSCORE` at render time (`backend/marketdata/pair_series.py`), not the strategy's stored `entry_threshold`. The trade's true entry z (3.19) is labelled separately. So don't read the "+entry 1.5" line as this strategy's entry — it used 3.

**Rank #1 total Net P&L — re-verified:**
- Identity (`backend/backtest/engine.py:448-450`): `net_pnl = final_capital − starting_capital = 11,864.90 − 10,000.00 = **$1,864.90**` ✓ (matches the headline; equity curve ends ≈ $11,864).
- Per-window cross-check (Net P&L = Σ per-window net_pnl): the 10 windows visible in the screenshots — W0 −30.34, W1 −168.92, W2 +19.95, W3 +1,283.73, W4 −873.83, W8 −0.90, W9 −24.74, W10 −433.66, W11 +824.67, W12 −92.34 — **sum to +$503.62**. So the 3 windows I can't see (W5–W7, trade windows ≈ 04-26→05-17) must total `1,864.90 − 503.62 = **+$1,361.28**`, which matches the **steep equity-curve climb in late-Apr→mid-May**. Internally consistent.
- Win rate `= trades with net_pnl>0 / total = 63%` of 9,439 (schema `win_rate`). An exact trade-level sum of all 9,439 `net_pnl` values would need a prod DB read (auto-mode blocked) — offered if you want the last-cent confirmation, but the identity + window sum already confirm the total is right.

---

## 2026-07-16 — What is the "Exit-|Z| sweep" and what's its purpose?

**Q:** [Re: my offer to "run the Exit-|Z| sweep on prod to empirically settle the 'wait longer?' question"] — yes to committing/pushing, but I didn't understand the purpose of the Exit-|Z| sweep.

**A:** The question "should 0G/MET have waited longer to exit?" can't be answered from **one** trade — waiting longer helps trades that keep reverting (like 0G/MET) and hurts trades that stall or re-diverge (extra funding + more stop-outs). A **sweep** settles it with data instead of intuition.

**What "waiting longer" means mechanically:** the exit is controlled by a single number — **Exit |Z|** (rank #1 uses `0.5`). The position closes when the spread has reverted to within `|z| < Exit |Z|` of its mean. **Lowering that number = waiting longer** (closer to full reversion, `z→0`); raising it = exiting earlier. It's a real per-strategy field (`exit_threshold`, `routers/backtest.py`; range `>0…2.0`).

**What the sweep is:** create a few copies of rank #1 that are **identical except for Exit |Z|**, run them all on the same Hyperliquid data, and compare:

| Strategy | Exit \|Z\| | Behaviour |
|---|---|---|
| rank #1 (baseline) | **0.5** | exits ~halfway back to the mean (what 0G/MET did) |
| clone A | **0.3** | waits a bit longer |
| clone B | **0.1** | waits until *almost fully* reverted (≈ what 0G/MET "should" have done) |

Then compare **Net P&L, win-rate, average hold time, and funding drag** across all ~9,439 trades. That tells you empirically whether "waiting longer" actually earns more *for the strategy* — or whether the extra funding + the trades that stall eat the gains from the ones that keep reverting.

**Why it's the right tool:** 0G/MET *looks* like it should have waited, but that's survivorship bias — we can see, in hindsight, that it kept reverting. The sweep removes the bias by applying the rule change to **every** trade at once, turning "this one trade suggests X" into "changing Exit |Z| to 0.1 moves the total from $1,864.90 to $Y."

**The catch:** running it **creates and runs new backtest strategies on the live production box** (each is a heavy multi-window sweep). Not destructive and it doesn't touch the bot's trading state, but it consumes prod compute and adds strategies to the list — so it needs an explicit go-ahead. (Alternatively, the operator can run it in the UI: clone rank #1 three times, set Exit |Z| to 0.5 / 0.3 / 0.1, run, compare.)

---

## 2026-07-16 — Exit-|Z| sweep RESULT: does waiting longer pay? (yes — my prediction was wrong)

**Q:** [Ran the sweep on prod: three clones of rank #1, identical except Exit |Z| = 0.5 / 0.3 / 0.1, on Hyperliquid.] What's the verdict — should trades wait longer to exit?

**A:** **Waiting longer WON, decisively — Net P&L rose monotonically as the exit tightened. The user's original 0G/MET intuition was right, and my earlier hypothesis (that funding + time-stops would eat the gains) was wrong.**

| Exit \|Z\| | Net P&L | Win rate | Trades | Avg $/trade |
|---|---|---|---|---|
| **0.5** (rank #1 baseline) | $1,864.90 | 63.24% | 9,439 | $0.198 |
| **0.3** | $2,144.79 | 63.01% | 9,161 | $0.234 |
| **0.1** | **$2,485.15** | 60.89% | 8,231 | **$0.302** |

- **0.5 → 0.3: +$279.89 (+15.0%). 0.3 → 0.1: +$340.37 (+15.9%). 0.5 → 0.1: +$620.26 (+33.3%).**
- **Sanity check passed:** `sweep-exit-0.5` reproduced rank #1 to the cent (net_pnl `1864.896495` ≈ $1,864.90, win 63.24%) — the clone is faithful, so the comparison is valid.

**Mechanism (as the running exit-mix polls foreshadowed):** tightening the exit does exactly what was predicted on the *cost* side — fewer trades (9,439 → 8,231, positions held longer so fewer round-trips), a slightly lower win-rate (63.24% → 60.89%, some trades never reach the stricter `|z|` target and close on the time-stop/window-end), and far more Time-stops (mid-run: 27 → 401 for 0.1). **What I got wrong: the deeper reversion captured on the winners more than paid for all of that.** Average $/trade rose +53% (0.198 → 0.302). Fewer, higher-quality captures beat more, shallower ones — the spread on Hyperliquid reverts far enough, often enough, that leaving the exit at 0.5 was systematically taking profit too early. So 0G/MET wasn't survivorship bias; it was representative.

**Recommendation:**
- **Tighten rank #1's exit toward ~0.1** (net +33% on this span). Consider a **finer sweep (0.05 / 0.1 / 0.15 / 0.2)** to find the true optimum — the monotone trend suggests even tighter *might* help, but there's a floor (`exit_threshold > 0`) and funding/drawdown eventually bite.
- **Don't adopt on this alone.** (1) It's **one Hyperliquid walk-forward span** — re-run on a different date range before trusting (curve-fit risk). (2) Higher *final* P&L ≠ lower risk: exit 0.1 holds longer (more funding, more capital tied up), so check the **equity-curve shape and max drawdown**, not just the total. (3) Live slippage is worse than backtest; longer holds face more funding variance live.

**Method note:** run as three heavy Hyperliquid backtests. Three at once **starved the DB connection pool** (a 60s read timeout + slow progress, issue #168); they still finished, but for reliability run heavy sweeps **one at a time** or bump the pool further.

---

## 2026-07-19 — Finer Exit-|Z| sweep (0.05–0.5) DEBUNKS the coarse result: the exit is a noise lever

**Q:** [Ran a finer sweep — added Exit |Z| = 0.05 / 0.15 / 0.2 to the earlier 0.1 / 0.3 / 0.5, one at a time — and pulled max drawdown for all six.] What's the real optimum, and is exit 0.1's win robust?

**A:** **It isn't robust. The finer sweep overturns the clean "+33% by tightening" story from the 3-point sweep — for this strategy, on this span, the exit threshold is a *noise* lever, not a profit lever.**

Full curve (rank #1 cloned, **only** Exit |Z| varied, Hyperliquid, one walk-forward span):

| Exit \|Z\| | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| 0.05 | $2,127 | 58.7% | 7,541 | 12.40% |
| **0.10** | **$2,485** ← spike | 60.9% | 8,231 | 11.93% |
| 0.15 | $2,051 | 61.6% | 8,608 | 11.37% |
| **0.20** | **$1,850** ← worst (below baseline!) | 62.3% | 8,829 | 11.57% |
| 0.30 | $2,145 | 63.0% | 9,161 | 11.42% |
| 0.50 (baseline) | $1,865 | 63.2% | 9,439 | 12.70% |

**What's real (smooth, monotonic — the *mechanical* effects):**
- **Win rate** rises steadily as the exit loosens (58.7% → 63.2%): a looser target is easier to hit, so more trades close as clean take-profits.
- **Trade count** rises steadily as the exit loosens (7,541 → 9,439): looser exits close sooner, so more round-trips fit per window.
- **Max drawdown** is basically flat (~11.4–12.7%) across all six — the exit doesn't meaningfully change the risk profile.

**What's NOT real (jagged — noise):** **Net P&L** bounces with no trend: $2,127 → $2,485 → $2,051 → $1,850 → $2,145 → $1,865. The **best (0.1) and the worst (0.2) sit right next to each other**, and 0.2 actually *underperforms* the do-nothing baseline. Statistically the six nets are **$2,087 ± $212 (1σ)**; 0.1 is a **+1.9σ** outlier and 0.2 a −1.1σ one. With **n = 1 span**, a lone 2σ bump is exactly what noise looks like — not a discovered optimum.

**Analogy — the mountain in the fog.** The coarse 3-point sweep (0.5 → 0.3 → 0.1) was like glimpsing three rocks up a foggy hillside, each higher than the last, and concluding *"there's a smooth slope to a summit at 0.1 — let's climb it."* The finer sweep cleared the fog: the ground isn't a slope at all, it's a **bumpy rock field**. The "summit" at 0.1 is just a boulder that happened to be tall, and one step over (0.2) is a **ditch lower than where we started**. Retuning the exit to 0.1 is chasing a rock you found by luck — on a different month's terrain it won't be there. *(Put another way: win-rate and trade-count are a clear radio signal; net P&L is the dial tuned between stations — mostly static, and the 0.1 "peak" is just the loudest crackle.)*

**The honest arc of this investigation (worth keeping):** (1) I predicted waiting longer wouldn't pay. (2) The **3-point** sweep showed a clean monotone +33% and I said *"I was wrong."* (3) The **6-point** sweep shows step 2 was itself the mistake — the +33% was an artifact of sampling three points that happened to ascend. The exit lever is weak; my original skepticism was closer to right, but for a new reason (noise, not funding).

**Recommendation:**
- **Do NOT retune the exit off this.** Keep a sensible default — **0.5** (do-nothing) or **0.3** (more trades, near-identical P&L, lowest-ish DD) are both fine; the gap between them is inside the noise. Don't ship 0.1.
- **The edge, if any, is elsewhere** — sweep **entry threshold**, **pair quality (p-value)**, **half-life filter**, **trade window**, or **costs** next. The exit is not where this strategy's money is made or lost.
- **Method lesson (the real prize):** a coarse sweep can *fabricate* a trend. Sample any parameter finely enough to see whether an apparent monotone "win" survives, and **re-validate across multiple date spans** before trusting any single-point optimum — a 2σ bump on one span is not a signal.

---

## 2026-07-19 — Entry-|Z| sweep: a REAL lever (unlike exit) — selectivity is survival

**Q:** [Swept Entry |Z| = 1.5 / 2.0 / 2.5 / 3.0 / 3.5 on Hyperliquid, all else = rank #1, one at a time, with drawdowns.] Is the entry threshold a real lever, and what should it be?

**A:** **Yes — and it is the strongest, cleanest lever we have found. The opposite of the exit (which was noise): here the signal is ~37σ above the noise floor, and it says be *ruthlessly selective*.**

| Entry \|Z\| | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| 1.5 | **-$5,021** | 60.0% | 18,240 | **51.1%** |
| 2.0 | **-$5,316** | 59.4% | 15,842 | **53.2%** |
| 2.5 | **-$5,640** | 60.5% | 13,269 | **62.3%** |
| 3.0 | **+$1,865** | 63.2% | 9,439 | 12.7% |
| 3.5 | **+$2,307** | 66.1% | 2,940 | **8.9%** |

**Findings:**
- **A real regime boundary at ~3.0, not an overfit spike.** Earlier I worried the +$1,865 at exactly rank #1's value (3.0) was curve-fit. It is not: **3.5 is even better on every axis** — higher net (+$2,307, +24% over 3.0), higher win rate (66.1%), and *lower* drawdown (8.9% vs 12.7%). Both high-entry values are solidly positive; all three low values are catastrophic. If 3.0 were a lucky spike, 3.5 would have fallen — it climbed.
- **Below ~3.0 it is not just unprofitable, it is RUINOUS.** Entry 1.5/2.0/2.5 lose ~$5k *and* suffer **51-62% drawdowns** — the account roughly halves. High entry (3.0/3.5) keeps drawdown to 9-13%.
- **The swing is ~37σ** ($7,947 from worst to best vs the $212 exit-noise floor). This is signal, not scatter — and it is *monotonic in the meaningful direction* (more selective = better return AND lower risk).
- Determinism confirmed: entry-sweep-3.0 reproduced rank #1 to the cent ($1,864.896495).

**Why (mechanism):** a moderate dislocation (|z| 1.5-3) is often *not* a real over-extension — the spread just as easily keeps drifting toward the stop as it reverts. Trade thousands of those and you bleed fees+funding on coin-flips with fat left tails (hence the 50%+ drawdowns). Only the **extreme** dislocations (|z|>=3) are stretched far enough that the "leash" reliably snaps them back.

**Analogy — wait for the fat pitch.** A batter who swings at every pitch (entry 1.5) strikes out constantly and bleeds; a disciplined hitter who swings only at the rare perfect pitch (entry 3.5) — far fewer swings, but each one connects. The mediocre pitches in between (the 2.5-3.0 band) are exactly where you strike out. In this strategy, *not trading* the moderate signals is where the money is.

**Recommendation:**
- **Use a HIGH entry threshold — 3.0, and 3.5 was better here (more profit, higher win rate, lower drawdown).** Never run entry <= 2.5 (ruinous). This contrasts sharply with the exit (keep default 0.5) and the stop (keep 4, weak lever).
- Worth a quick follow-up: entry **3.5 vs 3.75 vs ~4.0** (the cap) to see if selectivity keeps paying — but note trade count is already thin at 3.5 (2,940), so higher = fewer samples = more per-run variance.
- **Still one span.** The direction (high selectivity wins) is robust and mechanically sensible, but the exact best value (3.0 vs 3.5) should be **re-validated across 2-3 other date ranges** before committing live. And 3.5's low trade count means its edge rests on fewer bets.

**Contrast with the exit sweep (2026-07-19 finer entry):** exit |Z| was a *noise* lever (differences within +/-$212, keep the default); entry |Z| is a *dominant* lever ($7.9k swing, be selective). When tuning this strategy, **spend your effort on the entry bar and pair quality, not the exit.**

---

## 2026-07-19 — Entry-|Z| pushed higher (3.5 / 3.75 / 4.0): selectivity has a CEILING — net P&L peaks at 3.5

**Q:** [Follow-up to the entry sweep: pushed the entry bar higher — 3.5 / 3.75 / 4.0, all else = rank #1, one at a time, on Hyperliquid.] Does being *even more* selective keep paying, or does the thin trade count break it down?

**A:** **It breaks down. Selectivity has a ceiling: net P&L is single-peaked at entry 3.5, then FALLS as you push higher — even though every per-trade quality metric keeps improving. "More selective = more money" is false past ~3.5; the collapsing trade count wins.**

Full profitable-band curve (rank #1 cloned, only Entry |Z| varied — and, for 4.0, Stop bumped 4→5 to avoid the degenerate entry==stop; Stop is a weak lever so this doesn't confound; Hyperliquid, one span 2026-03-01→06-23):

| Entry \|Z\| | Net P&L | Win % | Trades | **Avg $/trade** | Max DD |
|---|---|---|---|---|---|
| 3.0 | +$1,865 | 63.2% | 9,439 | $0.198 | 12.7% |
| **3.5** | **+$2,307** ← peak | 66.1% | 2,940 | $0.785 | 8.9% |
| 3.75 | +$1,916 | 63.9% | 1,209 | $1.585 | 3.88% |
| 4.0 | +$1,020 ← lowest of the profitable set | **84.0%** | **387** | $2.635 | 2.36% |

**The mechanism — decompose `net = trades × avg $/trade`:**
- **Per-trade quality rises monotonically** as the bar goes up: avg $/trade $0.198 → $0.785 → $1.585 → $2.635 (each rarer |z|≥bar dislocation is stretched further, so it reverts bigger). Win rate climbs to **84%** at 4.0, and max drawdown falls to a tiny **2.36%**. Every "is each trade good?" metric says *higher is better*.
- **But trade count collapses faster than quality rises:** 9,439 → 2,940 → 1,209 → **387**. Multiply it out — 3.0→3.5 net ×1.23 (quality gain wins), 3.5→3.75 ×0.83, 3.75→4.0 ×0.53 (volume loss dominates hard). The crossover where the marginal quality gain stops outpacing the marginal trade-count loss lands right at **~3.5**. That's why 3.5 is the optimum, not an accident.
- **4.0's 84% win rate is a vanity metric.** 387 trades × 84% still made only **$1,020** — less than half of 3.5's $2,307. **Win rate up, dollars down.** And 387 bets is dangerously thin: at that point the "edge" rests on almost no samples, so its per-run variance is large and its tiny 2.36% drawdown is just "the account barely moved because it barely traded," not genuine safety.

**Which axes are real vs noisy (same lesson as the exit sweep):** the *mechanical* axes — trade count ↓, avg $/trade ↑, drawdown ↓ — are perfectly monotone and trustworthy. **Net P&L is the noisy money axis**, and here it traces a clean inverted-U with its top at 3.5. (These higher-bar runs are *thinner* than the 9k-trade baseline, so their per-run noise is *wider* than the ±$212 floor measured on thick runs — another reason not to over-read the exact 3.5-vs-3.75 gap. But the *shape* — a profitable plateau 3.0–3.75 then a clear drop at 4.0 as trades hit 387 — is robust and mechanically forced.)

**Analogy — the batter who almost never swings.** Entry 3.5 is the disciplined hitter who swings at every *fat* pitch: fewer swings than the hacker (entry 1.5), but they connect, and across a season they drive in the most runs. Push to entry 4.0 and you get the batter so impossibly picky he swings maybe once a game — **84% of those rare swings are hits** (gorgeous batting average!), but he drives in *fewer total runs* than the 3.5 hitter, because he's barely at the plate. Precision is not productivity. There's a discipline sweet spot: selective enough that your swings connect, *not* so selective you forfeit your at-bats. *(Same shape as a hiring bar: raise the minimum past a point and every hire is superb, but you hire so few that total output drops.)*

**How this refines the earlier entry finding:** the prior sweep (1.5→3.5) established the *direction* — be selective, never ≤2.5 (ruinous, −$5k / 50–62% DD). This one finds the *interior optimum* inside the profitable band: it's **not** "monotone up, keep climbing" — it's a single peak at **~3.5**, with a soft profitable plateau from 3.0 to 3.75 and a clear falloff by 4.0.

**Recommendation:**
- **Set entry = 3.5 (the peak).** Best net P&L, strong 66% win, low 8.9% drawdown, and still **2,940 trades** — selective enough to be profitable, thick enough to trust. **3.0 is the robust fallback** (3× the trades = more statistical footing, ~$440 less P&L on this span).
- **Do not push above 3.5.** 3.75/4.0 improve the risk optics but *starve* the strategy — total P&L erodes and the sample gets too thin to trust. The entry hunt is **done**; 3.5 is the answer.
- **Next lever = pair quality**, not entry. Sweep **p-value** (base is a tight 0.01; try 0.05 / 0.10) and **max half-life** — the other likely-real lever. Then **re-validate entry 3.5 across 2–3 other date spans** before trusting it live (still one span; 3.5's edge rests on 2,940 bets).

---

## 2026-07-20 — Pair-quality (p-value) sweep: keep the cointegration gate TIGHT (0.01); the knob saturates at 0.05

**Q:** [Swept `pvalue_max` = 0.05 / 0.10 / 0.15 on Hyperliquid, all else = rank #1 (entry 3.0, p-value 0.01 baseline), one at a time.] Is the pair-admission p-value a real lever, and should we loosen it to trade more pairs?

**A:** **It's a real, dominant lever — and it says the exact opposite of "loosen." Keeping the cointegration gate TIGHT (0.01) is what makes the strategy profitable; loosening it to 0.05 flips it from +$1,865 to −$1,176. And the knob is inert past 0.05 — there's a hard-wired second gate the p-value cap can't loosen.**

| p-value (`pvalue_max`) | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| **0.01** (rank #1 baseline) | **+$1,865** | 63.2% | 9,439 | 12.7% |
| 0.05 | **−$1,176** | 61.6% | 15,208 | 24.19% |
| 0.10 | −$1,176 | 61.6% | 15,208 | 24.19% |
| 0.15 | −$1,176 | 61.6% | 15,208 | 24.19% |

**Two findings, one mechanism:**

1. **Loosening 0.01 → 0.05 is destructive.** Net swings **~$3,041** (from +$1,865 to −$1,176), trade count jumps **+61%** (9,439 → 15,208), and **drawdown nearly doubles** (12.7% → 24.19%). The marginal pairs admitted between p=0.01 and p=0.05 are net-losing: they're only *weakly* cointegrated, so their spreads don't reliably revert — they wander, hit stops, and bleed fees+funding. This is a **quality gate**, and like the entry threshold, it wants **selectivity**.

2. **The knob saturates at 0.05 — 0.05 / 0.10 / 0.15 are identical to the cent** (−$1,176.245516, 15,208 trades, 24.19% DD, all three). The engine is fully deterministic, so identical output = identical pair set: **loosening past 0.05 admits zero additional pairs.** The reason is in the code — a pair is admitted only if **`p_value < pvalue_max` AND `t_statistic < critical_value_5pct`** (`backend/statcore/cointegration.py:59`). That second condition is a **hard-wired 5%-confidence gate the `pvalue_max` dial cannot loosen.** So for any `pvalue_max ≥ 0.05`, the fixed 5% t-stat gate binds and the set is frozen; only a `pvalue_max < 0.05` (like rank #1's 0.01) tightens *past* it and cuts the pool down to the highest-confidence pairs.

**So the effective p-value control is one-directional:** you can demand *more* confidence than the built-in 95% floor (0.01 → trade only ~99%-confident tethers), but you cannot demand *less* (anything ≥0.05 = "use the default 95% gate"). rank #1 demands 99%, and that strictness is a load-bearing part of its edge.

**Analogy — two bouncers at the door.** Getting a pair onto the trading floor means clearing two bouncers. Bouncer #2 is permanent and never moves: he only admits pairs that are cointegrated at **95% confidence** (the fixed 5% t-stat gate). Bouncer #1 is the `pvalue_max` dial. Set him to **0.01** and he's *stricter* than #2 — he demands **99% confidence**, turning away the merely-95%-sure pairs. That strictness is the whole game: the pairs between 95% and 99% confidence (the crowd you let in by moving the dial 0.01 → 0.05) look tethered but their tether is borderline, and **borderline tethers snap** — they cost you $3k and double your drawdown. Move the dial *looser* than 0.05 and nothing happens: bouncer #2 is already turning away everyone past 95%, so there's no one left outside to admit. **Keep bouncer #1 strict at 0.01.**

**How this fits the campaign — the edge lives in selectivity, on two independent axes:**
- **Entry |Z| (when to trade an admitted pair):** be selective — 3.5 (peak), never ≤2.5.
- **p-value (which pairs are even allowed):** be selective — 0.01, never loosen.
- Both are *quality gates*, and both punish permissiveness. The money is made on the **small set of high-conviction, tightly-cointegrated pairs at extreme dislocations** — not on volume. Loosen *either* gate and you drown the edge in coin-flip trades. (Contrast the exit |Z|, still the lone *noise* lever — keep 0.5.)

**Recommendation:**
- **Keep `pvalue_max` = 0.01.** Do not loosen — 0.05+ is net-negative and past 0.05 the dial does nothing anyway.
- **Combine the two selectivity levers:** the candidate "best" config is **entry 3.5 + p-value 0.01** (+ exit 0.5 / stop 4). Worth a confirming run of that exact combo on this span, then the multi-span re-validation.
- **Half-life (`max_half_life_h`, base 72h) is the one pair-quality lever still un-swept** — tightening it (e.g. 48h / 24h) demands *faster*-reverting pairs and is the natural companion to the p-value gate. Next, alongside the entry-3.5 multi-span re-validation.

---

## 2026-07-20 — Multi-span re-validation of entry 3.5: the +$2,307 is CURVE-FIT (out-of-sample it's net-negative)

**Q:** [Ran the candidate best config — entry 3.5 + p-value 0.01 + exit 0.5 + stop 4, i.e. `entry-sweep-3.5` — on 3 other Hyperliquid date spans, to check the +$2,307 isn't curve-fit to the one 2026-03-01→06-23 window.] Does it hold up out-of-sample?

**A:** **No. The +$2,307 does not generalize — on the three earlier spans the same config nets −$536 in aggregate. The headline profit was the best of four noisy draws, selected *because* it was measured on the span it happened to win. This is a curve-fit, and it should NOT be trusted live.**

Same config (entry 3.5 / p-value 0.01 / exit 0.5 / stop 4 / scan 21 / trade 7 / zwin 21 / $10k), only the date span varied:

| Span | Window | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|---|
| **s1** (in-sample) | 2026-03-01→06-23 | **+$2,307** | 66.1% | 2,940 | 8.9% |
| s2 | 2025-11-07→2026-03-01 | −$170 | 66.1% | 3,593 | 17.57% |
| s3 | 2025-07-16→2025-11-07 | **−$1,313** | 61.9% | 2,652 | 22.35% |
| s4 | 2025-03-24→2025-07-16 | +$948 | 63.0% | 1,499 | 6.98% |

**The numbers that matter:**
- **Out-of-sample (s2+s3+s4) = −$536 net.** Two of the three OOS spans lose money; the one winner (s4, +$948) is outweighed by s3 (−$1,313). The 4-span total is positive (+$1,771) *only* because of the in-sample span, which was cherry-picked as "the best config" partly *because* it topped this exact window — classic selection bias / multiple-comparisons inflation.
- **Drawdown blows out OOS:** 8.9% in-sample → 17.6% / 22.4% on the two losing spans. Higher final P&L in-sample masked much worse risk out-of-sample.

**What's robust vs what isn't:**
- **Robust — the win rate (62–66% on every span).** The selectivity *mechanism* holds: a high entry bar reliably wins ~2/3 of trades regardless of regime. The earlier campaign findings (be selective on entry; keep p-value tight; low entry / loose p-value is *ruinous*) are directionally real — selectivity reliably prevents the 50–62% drawdown catastrophes of the permissive configs.
- **NOT robust — the dollar edge.** High win rate ≠ profit. On the losing spans the **average loss exceeds the average win**: most trades capture a small reversion, but a minority of pairs break cointegration and run to the stop (a **fat left tail**). Whether a span nets positive just depends on how many of those big losers it served up — s1/s4 few, s2/s3 many. That's regime luck, not a durable edge.

**Analogy — win-loss record vs point differential.** Entry 3.5 is a team that wins 63% of its games, but often by a single point while losing the rest by ten. Great *record*, negative *point differential*. It had a winning season (s1, s4) and a losing season (s3); you cannot call it a good team from its best season alone. One backtest span is one season; re-validating across four seasons showed the *average* season is roughly breakeven-to-negative after costs. **The single-span +$2,307 was survivorship at the strategy level — the same illusion the 3-point exit sweep created, now caught at the config level.**

**Conclusion for the campaign:**
- **Do NOT trust entry 3.5 / rank #1 live on this evidence.** Its profitability is regime-dependent; out-of-sample it is net-negative after costs.
- The selectivity levers (entry ≥3, p-value 0.01) are **necessary but not sufficient** — they buy *survival* (small drawdown, high win rate), not *profit*. The edge, if one exists, is thin and currently swamped by the left-tail losers.
- **Method win:** this is precisely why single-span optima must be re-validated across multiple spans before trusting them. Re-validation just prevented shipping a curve-fit config to real money. (Reinforces the exit-sweep method lesson: sample finely *and* out-of-sample.)

**Where to go next (open questions, not yet answered):**
1. **Is a less-selective config more *robust*?** Re-run **entry 3.0** (3× the trades → more diversification, less reliance on a few bets) across s2/s3/s4 — a steadier, if lower-peak, config may survive OOS where 3.5 doesn't.
2. **Attack the fat left tail directly** — the losses come from pairs breaking cointegration and running to the stop. Levers: tighter **half-life** (`max_half_life_h` 72h→24–48h, demand faster reversion), a tighter **z-stop**, per-trade risk caps, or a mid-trade cointegration re-check. That's where a *structural* edge would come from, if any.
3. **Accept the honest read:** naive Hyperliquid stat-arb over 2025–26 is ~breakeven after costs (matches `BACKTEST_PARAMETER_GUIDE.md:80-83`). Any live deployment needs a left-tail fix first, or acceptance of breakeven-with-variance.

---

## 2026-07-20 — Entry 3.0 out-of-sample: strictly worse than 3.5 — diversification hypothesis rejected, selectivity confirmed, family still OOS-negative

**Q:** [Open question #1 from the re-validation: is the *less*-selective config more robust? Re-ran entry 3.0 (3× the trades → more diversification) on the same 3 OOS spans s2/s3/s4.] Does more volume survive out-of-sample where 3.5 didn't?

**A:** **No — the opposite. Entry 3.0 is strictly worse than 3.5 on every span, in-sample and all three out-of-sample, on both net P&L and drawdown. The "more trades = more diversification = more robust" idea is dead. Selectivity is confirmed as robustly correct — but no entry threshold makes the family profitable OOS. The deficit is structural (the left tail), not a tuning knob.**

| Span | entry 3.0 (net / DD) | entry 3.5 (net / DD) | Winner |
|---|---|---|---|
| s1 (in-sample) | +$1,865 / 12.7% | +$2,307 / 8.9% | 3.5 |
| s2 | −$1,289 / **37.68%** | −$170 / 17.57% | 3.5 |
| s3 | −$3,334 / **41.54%** | −$1,313 / 22.35% | 3.5 |
| s4 | −$822 / 14.76% | +$948 / 6.98% | 3.5 |
| **OOS sum (s2+s3+s4)** | **−$5,445** | **−$536** | 3.5 |

(entry 3.0 trade counts: 11,308 / 7,962 / 6,205; win rates 65.1% / 60.3% / 61.8% — still >50%, still not profitable.)

**Two conclusions:**

1. **Selectivity is robustly correct — the campaign's most generalizable result.** Entry 3.5 beats 3.0 on *all four spans*, on *both* axes. It's monotone and universal, not curve-fit. Entry 3.0 is **3-for-3 negative OOS** with **38–42% drawdowns** (the account nearly halved on s2/s3). The extra ~8k trades/span are the marginal |z| 3–3.5 signals the original entry sweep already flagged as low-quality; out-of-sample they don't diversify the risk, they *amplify* it — more coin-flip trades with fat left tails digging a much deeper hole. So "be selective, never lower the entry bar" is **confirmed decisively.** (This is the robust half of the entry finding; the *specific* peak value 3.5 was the curve-fit half.)

2. **But no entry threshold makes the family OOS-profitable.** 3.5 is merely "least bad" (−$536); 3.0 is a disaster (−$5,445). Even s4 — 3.5's one OOS winner (+$948) — flips to −$822 at 3.0. Changing the entry bar only changes *how many marginal trades you pile on*; it cannot reach into the **left tail** (pairs breaking cointegration → running to the stop) where the OOS losses actually live. **That's a structural problem, not a parameter.**

**Why drawdown makes the case vivid:** entry 3.0 doesn't just lose more, it drags you through a **42% gorge** to do it — unsurvivable in practice (you'd bail or margin-call at the bottom). 3.5 walks shallower 7–22% valleys *and* ends less red. Among these trails 3.5 is unambiguously the one to walk — but **none of them summit.** (Analogy: max drawdown = the deepest valley on the hike; final P&L = only whether you ended higher than you started. A route with a terrifying gorge is dangerous even if it ends at the same altitude.)

**Consequence for the campaign — the only lever left is structural.** Entry and p-value are both exhausted: selectivity is *necessary* (prevents ruin) but not *sufficient* (no setting is OOS-profitable). The next and last experiment must target the **left tail directly** — tighten `max_half_life_h` (72h → 24/48h: demand faster-reverting pairs, which break cointegration less often and reach the take-profit before the stop) or tighten the z-stop. If that doesn't create a durable OOS edge, the honest conclusion is that naive Hyperliquid stat-arb over 2025–26 is breakeven-at-best after costs, and live deployment is not justified without a structural redesign.

---

## 2026-07-21 — Left-tail attack (half-life + z-stop): both are non-levers — EVERY parameter is now exhausted

**Q:** [Final campaign step: attack the fat left tail directly on **s3**, the worst OOS span (entry 3.5 → −$1,313 / 22.35% DD). Swept `max_half_life_h` = 72/48/24 and `stop_threshold` = 3.75/4.0/6.0, all else fixed.] Can a structural parameter fix the out-of-sample losses?

**A:** **No. Neither lever works, and for two different (and both instructive) reasons. Combined with the earlier sweeps, this exhausts every parameter the strategy exposes — none of them turns an OOS-negative span positive. The strategy family has no durable parametric edge on Hyperliquid 2025–26.**

**Half-life (`max_half_life_h`) — a NON-BINDING filter (inert):**

| Half-life cap | Net | Win % | Trades | Max DD |
|---|---|---|---|---|
| 72h (baseline) | −$1,313 | 61.9% | 2,652 | 22.35% |
| 48h | −$1,326 | 61.9% | 2,636 | 22.40% |
| 24h | −$1,348 | 62.1% | 2,551 | 22.88% |

Tightening all the way to 24h removed only **~4% of trades** (2,652 → 2,551) and left drawdown **flat-to-worse** (22.35% → 22.88%) with net marginally *worse*. The cap barely binds — pairs that clear the cointegration + p-value gates **already revert in under 24h**. (Same shape as the p-value saturation: a filter set looser than the binding constraint does nothing.) **Decisive implication: the OOS losses are NOT from slow-reverting pairs.** The losers revert *fast* — a subset simply **breaks** (cointegration fails) instead of reverting, and no formation-window statistic can predict *which* fast pair will break out-of-sample.

**Z-stop (`stop_threshold`) — a pure RISK/RETURN TRADE-OFF (no free lunch):**

| Stop \|Z\| | Net | Win % | Trades | Max DD |
|---|---|---|---|---|
| 3.75 (tight) | −$1,664 | 61.8% | 2,669 | **20.62%** |
| 4.0 (baseline) | −$1,313 | 61.9% | 2,652 | 22.35% |
| 6.0 (wide) | **−$1,290** | 61.9% | 2,634 | **24.28%** |

Widening the stop improves net (−$1,664 → −$1,290) but worsens drawdown (20.6% → 24.3%) in lockstep — **no setting improves both**, and the best net beats baseline by **$23** (deep inside noise) while costing 2 points of drawdown. Notably the **tight** stop is *worse* on net, which **refutes the "losers run to the stop" hypothesis**: trades that dip to |z|=3.75 against you mostly *come back*, so a tight leash just books would-be reverters as realized losses. The tail isn't trades running *past* the stop — it's trades losing on their own merits during the hold and exiting underwater via the time-stop/window-end.

**Analogy — the see-saw and the thermostat.** The z-stop is a **see-saw**: push one end down (tighter stop → lower drawdown) and the other rises (worse net); push the other way and it reverses. You can tilt it all day, but you never *lift* it — the whole see-saw sits below the waterline on this span. And the half-life cap is a **thermostat in a house with no heater**: you can turn the dial anywhere you like and nothing changes, because it was never the thing controlling the temperature.

**THE COMPLETE LEVER TAXONOMY (campaign conclusion):**

| Lever | Behaviour | Creates OOS edge? |
|---|---|---|
| Exit \|Z\| | noise (jagged, ±$212) | **No** |
| Entry \|Z\| | potent; selectivity robust (3.5 > 3.0 on all 4 spans) | **No** — OOS-negative at every value |
| p-value | potent *below* 0.05 (tight essential); saturates above | **No** — prevents ruin, can't create profit |
| Half-life | non-binding / inert | **No** |
| Stop \|Z\| | pure risk/return trade-off | **No** — slides along the frontier, doesn't shift it |

**Final honest verdict: no parameter in this strategy turns out-of-sample losses into profit.** The levers either don't bind, or merely trade one kind of pain for another, or (entry/p-value) buy *survival* without *profit*. **Naive Hyperliquid stat-arb over 2025–26 is breakeven-to-negative after costs out-of-sample — live deployment is NOT justified on this evidence.** (This matches the independent warning in `BACKTEST_PARAMETER_GUIDE.md:80-83` that naive crypto pairs are usually net-negative after costs.)

**The most promising untested lead — COSTS, not signal.** Round-trip friction is ~0.05% taker fee + 0.05% slippage per leg per fill × 4 fills ≈ **$0.40 per $100 trade** (`backend/simulation/costs.py`), against an observed average net of only **$0.20–$0.78/trade**. **Costs are the same order of magnitude as the entire edge** — so the strategy may be gross-positive but friction-negative. This is cheaply and decisively testable: re-run s3 with `taker_fee_pct` / `slippage_pct` cut (e.g. 0.05 → 0.02, a maker-style execution assumption) and see how much of the −$1,313 is friction vs signal. If a realistic cost reduction flips it positive, the productive work is **execution** (maker orders, better fills, fewer round-trips), not more parameter tuning. If it stays negative even at near-zero costs, the signal itself is dead and the strategy needs a fundamentally different edge.

**Other structural directions (untested, require code changes):** a **regime filter** (only trade when recent reversion quality is high — the losses cluster in regimes where pairs broadly stop reverting), a **mid-trade cointegration re-check** (exit when the relationship breaks, rather than waiting for the z-stop/time-stop), or **portfolio-level risk caps** (limit concurrent correlated pairs — what turns many small losses into a 22–42% drawdown).

---

## 2026-07-21 — COST DECOMPOSITION: the conclusion REVERSES — there IS a positive out-of-sample gross edge; friction destroys it

**Q:** [Diagnostic proposed after every parameter was exhausted: is the deficit *signal* or *friction*? Re-ran the best config (entry 3.5) on the OOS spans with `taker_fee_pct`/`slippage_pct` set to 0.02 and to 0.00, decomposing `net = gross − friction`.] How much of the out-of-sample loss is execution cost?

**A:** **Almost all of it — and this REVERSES the campaign's conclusion. The strategy has a genuine positive out-of-sample gross edge of +$2,554; friction of $3,090 destroys it. The earlier "no edge, don't deploy" verdict was wrong — it over-generalised from s3, which turned out to be the one flat span.**

**Measured decomposition (entry 3.5, all three OOS spans):**

| Span | Net (actual) | **Gross (measured, zero-friction)** | Friction | Max DD: net → gross |
|---|---|---|---|---|
| s2 | −$170 | **+$1,181** (69.1% win) | $1,352 | 17.57% → **10.14%** |
| s3 | −$1,313 | −$200 (66.4% win) | $1,113 | 22.35% → **14.48%** |
| s4 | +$948 | **+$1,573** (68.5% win) | $626 | 6.98% → **5.64%** |
| **OOS total** | **−$536** | **+$2,554** | **$3,090** | — |

The identity closes **exactly**: `$2,554 − $3,090 = −$536`, matching the actual OOS net to the cent. Friction ≈ **$0.398/trade** (measured consistently across spans: $0.375 / $0.416 / $0.417).

**The cost model is exactly linear** — the intermediate rung confirms it. On s3: 0.00 → −$200, 0.02 → −$648, 0.05 → −$1,313 (predicted −$645 vs actual −$648; and s4 gross predicted +$1,574 vs actual +$1,573.47, accurate to 53 cents).

**Break-even is close.** Friction scales linearly with the per-side rate, so OOS turns positive once it falls below **0.0413%** (from today's 0.05%) — a mere **17% cost reduction**. Beyond that:
- **0.02%** per side → OOS ≈ **+$1,318**
- **0.01%** (realistic maker fills) → OOS ≈ **+$1,936**
- **0.00%** → **+$2,554**

Note also that **friction inflates drawdown substantially** — removing it takes s2 from 17.6% → 10.1% and s3 from 22.4% → 14.5%. The risk profile at low cost is genuinely good (5.6–14.5%) with 66–69% win rates.

**THE DEEPER INSIGHT — "selectivity" was largely a FRICTION artifact.** Friction is a roughly *fixed ~$0.40 tax per trade*, so it disproportionately destroys low-edge-per-trade configurations. Reconstructing gross for the in-sample entry sweep with the measured constant:

| Entry \|Z\| | Net (s1) | Gross/trade | **Gross total (s1)** |
|---|---|---|---|
| 3.0 | +$1,865 | $0.60 | **+$5,612** |
| 3.5 | +$2,307 | $1.18 | +$3,474 |
| 3.75 | +$1,916 | $1.98 | +$2,396 |
| 4.0 | +$1,020 | $3.03 | +$1,174 |

**At zero cost, entry 3.0 is the BEST config, not the worst** — and this holds out-of-sample too (entry 3.0 OOS gross ≈ **+$4,668** vs entry 3.5's +$2,554, derived from the same constant). Entry 3.0 only *looked* catastrophic (−$5,445 OOS, 38–42% drawdowns) because it trades 3× as often and therefore pays 3× the friction. **The optimal entry threshold is a function of the cost level:** at high costs be ruthlessly selective (3.5+); at low costs trade far more (entry 3.0 overtakes 3.5 below roughly 0.015% per side). This reframes the campaign's headline "selectivity is the dominant lever" as substantially a *friction* finding — selectivity was the right response to an expensive execution assumption, not an intrinsic property of the signal.

**Analogy — a toll road.** Every trade pays the same ~$0.40 toll regardless of how far it travels. The signal generates real value on every trip, but the short trips (marginal |z| ≈ 3 dislocations, ~$0.60 of gross each) barely clear the toll, while long trips (|z| ≥ 4, ~$3 of gross) clear it easily. Raising the entry bar was simply *refusing to take short trips because the toll ate them* — sensible while the toll is high, but it also forgoes an enormous number of genuinely profitable journeys. **Lower the toll and the whole road network becomes worth driving.** The previous conclusion mistook "the tolls exceed our fares" for "nobody wants to travel."

**CORRECTED VERDICT:** the signal is **not** dead. It produces a real, out-of-sample-robust gross edge (3 of 4 spans strongly positive, good drawdowns, 66–69% win rates). **The entire deficit is execution cost.** The productive work is therefore **execution engineering, not parameter tuning** — a different and far more tractable problem.

**HONEST CAVEATS — this is not a free lunch:**
1. **Zero-cost is a counterfactual upper bound**, not an achievable strategy. It measures the edge; it is not a config you can run.
2. **Maker orders do not guarantee fills.** A two-legged pair trade with passive orders risks one leg filling and the other not — **legging risk** the backtest does not model (the failsafe-close path exists and itself costs money).
3. **Passive fills are adverse-selected** — you get filled precisely when the market moves against you. Simply lowering `slippage_pct` does **not** capture this; real maker execution carries its own hidden cost that could consume much of the modelled saving.
4. Funding **is** included in all gross figures (it is not zeroable via these params), so that drag is already accounted for.
5. The entry-3.0 gross figures are *derived* from the measured $0.398/trade constant, not directly measured. The constant is well-established (three spans, 0.375–0.417) but those specific numbers should be confirmed by direct runs before acting on them.

**NEXT STEPS (execution-focused, replacing the parameter roadmap):**
1. **Establish Hyperliquid's real fee schedule** — maker vs taker tiers, any rebates. This sets the achievable floor and tells us immediately whether the 0.0413% break-even is reachable.
2. **Validate the 0.05% slippage assumption against real fills** — it may be pessimistic (or optimistic) for these markets; the whole conclusion is sensitive to it.
3. **Directly measure entry 3.0 at low cost** on the OOS spans (confirm the +$4,668 derived figure), then re-derive the cost-dependent optimal entry.
4. **Model maker execution honestly** — fill probability, adverse selection, and legging risk — rather than just lowering `slippage_pct`. This is the crux: it decides whether the edge is harvestable.
5. Only then reconsider live deployment. The edge is real, but **"real gross edge" ≠ "profitable after realistic execution"** — that gap is exactly what step 4 measures.

---

## 2026-07-22 — Execution economics: real fees, MEASURED slippage, and the cost-dependent optimal entry

**Q:** [Three-step follow-up to the cost decomposition: (1) get Hyperliquid's real maker/taker fee schedule, (2) measure actual slippage rather than assuming 0.05%, (3) directly measure entry 3.0's gross to re-derive the cost-dependent optimal entry.] Is the edge harvestable, and at what entry threshold?

**A:** **Taker execution is a coin flip (+$187 OOS, inside the ±$212 noise floor). Maker execution is solidly profitable (+$1,114 even charging adverse selection at the full half-spread). And entry 3.5 remains the right config at every realistic cost level — entry 3.0's larger gross edge only wins under near-perfect execution.**

### 1. Hyperliquid's real fee schedule

| Tier (14-day volume) | Taker | Maker |
|---|---|---|
| **0 — base** | **0.045%** | **0.015%** |
| 1 (>$5M) | 0.040% | 0.012% |
| 2 (>$25M) | 0.035% | 0.008% |
| 3 (>$100M) | 0.030% | 0.004% |
| 4 (>$500M) | 0.028% | 0.000% |

Plus staking discounts 5–40% (Wood→Diamond) and maker rebates to −0.003% at top tiers. **Our modelled 0.05% taker was slightly pessimistic** (real base 0.045%), and **maker is 3× cheaper than taker** — the single most important number here.

### 2. Measured slippage (not assumed)

Queried Hyperliquid's live L2 order book for every coin the strategy actually trades, weighted by leg-fill count (**160 coins, 97% leg-fill coverage**). Half-spread is the correct slippage proxy: at **$100/leg** against top-of-book depth in the hundreds of thousands, market impact beyond the touch is negligible.

**Trade-weighted half-spread = 0.0316%** — median 0.0165%, P25 0.0086%, P75 0.0328%, P90 0.0615%, max 0.279% (worst: HMSTR 0.279%, BOME 0.243%, PURR 0.196%, NOT 0.135%, TURBO 0.120%).

So the modelled **0.05% slippage was too pessimistic** — real crossing cost is ~0.032%.

### 3. Measured gross by entry threshold, and the full economics

Direct zero-cost runs at both entry thresholds across the three OOS spans:

| Config | **Gross (measured)** | Friction @0.10% | Break-even rate | Zero-cost DD (s2/s3/s4) |
|---|---|---|---|---|
| entry 3.5 | +$2,554 | $3,090 | **0.0827%** | 10.1 / 14.5 / 5.6% |
| entry 3.0 | **+$4,379** | $9,825 | **0.0446%** | 26.6 / 22.3 / 8.7% |

*(entry 3.0 gross: s2 +$2,688, s3 −$158, s4 +$1,849. Consistency check: $4,379 − $9,825 = −$5,446, matching the measured entry-3.0 OOS net of −$5,445 exactly.)*

**Net under each execution regime** (friction scales linearly with fee+slippage per fill):

| Regime | Total/fill | **entry 3.5** | **entry 3.0** |
|---|---|---|---|
| Model assumption (0.05 + 0.05) | 0.100% | −$536 | −$5,446 |
| **Real taker** (0.045 + 0.0316) | 0.0766% | **+$187** | −$3,147 |
| Taker + 15% staking | 0.0699% | +$394 | −$2,489 |
| **Maker + full half-spread charged** (0.015 + 0.0316) | 0.0466% | **+$1,114** | −$199 |
| **Maker, no spread cost** (0.015 + 0) | 0.015% | +$2,091 | **+$2,905** |

### Conclusions

1. **Taker execution is not a business.** +$187 across three OOS spans sits *inside* the measured ±$212 single-span noise floor — statistically indistinguishable from zero. Even with 15% staking discounts it's +$394 on $10k over ~11 months (~4%/yr) with 17–22% drawdowns. Not worth the risk.
2. **Maker execution is where the edge lives.** At 0.015% fee, even charging adverse selection at the *full* half-spread (a deliberately pessimistic assumption — a resting order that fills has not crossed the spread) it returns **+$1,114**. The gap between taker and maker execution is worth ~**$1,900 OOS** — nearly 4× the strategy's entire net deficit. **This is an execution-quality story end to end.**
3. **Entry 3.5 remains the right config — my earlier "entry 3.0 is actually best" was over-stated.** True: entry 3.0 has **1.71× the gross edge**, confirming that friction (not signal) is what made it look catastrophic. But it also carries **3.2× the friction** and **~2× the drawdown**. Entry 3.0 only overtakes 3.5 below **0.0271% total per fill** — i.e. only under near-perfect execution. At realistic maker levels (0.0466%) entry 3.0 is still **negative** (−$199) while 3.5 makes +$1,114. Even where 3.0 wins on dollars it is worse risk-adjusted (gross/DD ≈ 228 vs 253). **So "selectivity was a friction artifact" holds for the *gross* ranking, but the *practical* ranking at achievable costs still favours 3.5.**

**Analogy — the toll road, revisited.** Earlier we found the toll (~$0.40/trade) was eating the fares, and that at zero toll the *scenic route* (entry 3.0, many short trips) generates the most total value. Measuring the real toll booth changes the picture: the toll is somewhat cheaper than feared (0.077% not 0.10%), and there is an **express lane** — maker orders at a third the price. But the scenic route only pays off if the toll is *nearly free*; at any realistic price the **direct route (entry 3.5) is still the one to drive**, because it makes far fewer toll-paying trips per dollar of value delivered.

### A cheap, high-leverage improvement discovered along the way

Slippage dispersion is wide (P90 = 0.0615%, worst 0.279%) and **the scan currently admits any cointegrated pair regardless of tradability**. Excluding coins above ~0.06% half-spread would cut trade-weighted slippage materially while losing relatively few trades — a **spread/liquidity filter on pair selection** is a cheap, targeted change and the natural companion to the maker work.

### Caveats

1. **Spreads are a current snapshot**, not historical spreads during the 2025 spans. The strategy enters at extreme |z| dislocations, which often coincide with volatility — when spreads *widen*. **The taker case above is therefore optimistic**, which makes the "taker is a coin flip" verdict, if anything, generous.
2. **Maker fill probability and legging risk remain unmodelled.** A resting two-legged order can fill on one side only; the failsafe-close path costs money. This is the single biggest unknown.
3. Adverse selection is charged as a flat half-spread in the table above — a crude proxy, not a measurement.

### Next steps
1. **Model maker execution honestly** — fill probability, adverse selection, legging risk. This is now *the* deciding question, and it needs code, not sweeps.
2. **Add a spread/liquidity filter** to pair selection (exclude >0.06% half-spread markets) and re-run — cheap and likely a direct improvement.
3. **Sample spreads during volatile periods**, not just calm ones, to de-bias the slippage estimate.
4. Live deployment remains unjustified until (1) resolves: **"real gross edge" ≠ "profitable after realistic execution."**

---

## 2026-07-22 — CORRECTION: the operator trades MARKET orders only — the maker path is off the table

**Q:** The previous entries recommend maker execution as the way to harvest the edge, and list "model maker execution honestly" as the deciding next step. But I will not use limit orders — I intend to **trade manually with MARKET orders**, picking a trade from the manual-trading section after a re-scan and executing at whatever price the exchange gives. Do the docs need correcting?

**A:** **Yes — corrected here. The maker analysis stays on record as valid analysis, but it is NOT available to this operator, so the taker row is the operative one: +$187 out-of-sample, which is statistically zero. The maker-modelling work is dropped.**

**1. The backtest already models market orders correctly — there is no modelling gap.** Verified in code: `taker_fee_pct` is charged on the filled notional of **every leg at both entry and exit**, and `apply_slippage()` moves each fill **adversely** — a BUY fills above the reference price, a SELL below (`backend/simulation/costs.py:49-51`, `_fill_leg`, `simulate_pair_entry`, `compute_exit_pnl`). That is precisely a market order crossing the spread. **There is no maker/limit assumption anywhere in the cost model.** So the simulator already represents the operator's intended execution, and the previously-proposed work — fill probability, legging risk, adverse selection on resting orders — is **irrelevant and is dropped**. None of it applies when you always cross.

**2. The operative economics are the taker row.**

| Regime | Total/fill | OOS net | Status |
|---|---|---|---|
| **Real taker (0.045% fee + 0.0316% spread)** | 0.0766% | **+$187** | ✅ **operative** |
| Maker + full half-spread | 0.0466% | +$1,114 | ❌ unavailable |
| Maker, no spread cost | 0.015% | +$2,091 | ❌ unavailable |

**+$187 across three OOS spans sits inside the ±$212 single-span noise floor — statistically indistinguishable from zero**, with 17–22% drawdowns. And it is the *optimistic* case: the 0.0316% half-spread was measured on **calm books**, whereas entries fire at extreme |z| dislocations, exactly when spreads widen. **On current evidence the strategy is not worth trading manually with market orders.**

**3. A second cost that is not in any number so far: market impact.** The measured half-spread assumes **$100/leg**, where top-of-book depth (often hundreds of thousands of dollars) makes impact negligible. Manual trading at meaningful size — $5–10k/leg — in thin alt perps (TURBO, SAGA, HMSTR) would **walk the book**, adding a cost that appears nowhere in this analysis and that scales *against* you as size grows. Bigger size does not scale the edge linearly; it erodes it.

**4. What could still make market-order manual trading viable — the one remaining lever.** Slippage is wildly dispersed: **P25 = 0.0086%, median = 0.0165%, mean = 0.0316%, worst = 0.279%.** The mean is dragged up by illiquid junk a human would never choose. Restricting to tight-spread markets — which is what manual selection naturally does — changes taker economics materially:

| Universe | Slippage | Total/fill | OOS net (gross held constant) |
|---|---|---|---|
| All markets (current) | 0.0316% | 0.0766% | +$187 |
| Median-and-better | 0.0165% | 0.0615% | **+$654** |
| Top-quartile liquidity | 0.0086% | 0.0536% | **+$898** |

**Two important caveats on that table:** (a) it holds **gross constant**, but narrowing the universe means fewer markets → fewer pairs → fewer trades → **less gross edge**, so the true net is uncertain and must be *measured*; (b) the backtest **cannot currently do this** — `_universe()` returns every available market with no liquidity filter (`backend/backtest/engine.py:604-606`), so it needs a small code change.

**Corrected roadmap:**
1. **Add a liquidity/spread filter to the backtest universe** and re-run entry 3.5 on the three OOS spans with real taker costs (fee 0.045%, slippage = the filtered universe's actual half-spread). **This is now the deciding experiment** — it answers "is this worth trading by hand with market orders?" with a measurement rather than an extrapolation.
2. **Add a market-impact / book-walking estimate** sized to the operator's actual per-leg notional.
3. **Sample spreads during volatile periods** to de-bias the slippage estimate toward the moments trades actually fire.
4. **Live remains unjustified** until (1) shows a durable positive net under taker costs.

**Method note (worth keeping):** this is the second time a stated constraint reversed the recommended direction — first the cost decomposition overturned "the signal is dead", now the market-order constraint overturns "maker execution is the whole game". Both prior conclusions were correct *given their assumptions*; both assumptions turned out not to match reality. **Establish the operator's actual execution constraints before optimising against a hypothetical one.**

---

## 2026-07-22 — Why does the dashboard show so many PROFITABLE strategies when the analysis says the strategy loses money?

**Q:** [Screenshot of `/dashboard/backtest` — "STRATEGIES 69", sorted by Net P&L descending, with the top 15 rows all green: $2,688 / $2,485 / $2,307 / $2,145 / $2,127 / $2,051 / $1,916 / $1,865 ×3 / $1,850 / $1,849 / $1,573 / $1,181 / $1,020.] Based on everything you ran, why does the dashboard show so many positive/profitable net results, when your terminal analysis kept reporting negative, disheartening ones? Explain with simple analogies.

**A:** **Nothing on the dashboard is wrong. It faithfully answers "what did this run produce?" — but that is a different question from "would this make money going forward?" Three things separate the two, and the leaderboard shows none of them.**

**1. The list is sorted best-first — you are looking at a winners' podium, not a summary.** Every loss is still in that list of 69, just scrolled below the fold: **−$5,445, −$3,334, −$1,313, −$1,289, −$822, −$170**. *Analogy — the casino's "Today's Winners" board:* it glows with jackpot photos, and nobody is lying; the losers simply don't get a line on the board.

**2. Categorise the visible top 15 and the answer falls out immediately:**

| What it actually is | Count | Examples from the screenshot |
|---|---|---|
| **In-sample** (the single 2026-03-01→06-23 window) | **11** | `entry-sweep-3.5 $2,307`, `sweep-exit-0.1 $2,485`, `Untitled strategy $1,864.90` |
| **Zero-cost counterfactuals** (fees + slippage set to 0) | **4** | `cost000-e30-s2 $2,688`, `cost-000-s4 $1,573`, `cost-000-s2 $1,181` |
| **Realistic *and* out-of-sample** | **0** | — |

**Not one row in the visible top 15 is a realistic out-of-sample result.** That is the whole answer in one table.

- The **in-sample** rows all ran on the *same* date window — the one span that happened to be a good regime for this strategy. *Analogy — auditioning with the one song you have practised for months:* you will sound brilliant, and it tells the panel nothing about sight-reading. The out-of-sample spans were the sight-reading test, and that is where it fell apart.
- The **zero-cost** rows exist only to isolate the raw signal by removing friction. They are **diagnostics, not strategies** — untradeable, because you cannot trade for free. *Analogy — a car's top speed measured in a vacuum:* a real, useful physics number, and not how fast you will get to work.

**3. Sixty-nine attempts.** Searching 69 configurations and admiring the best is not the same as finding an edge; with that many tries the leader is partly just the luckiest draw. *Analogy — 69 people each flip 10 coins:* someone gets 9 heads, and a sorted leaderboard invites you to crown them "the gifted flipper."

**The honest scorecard — the same config (entry 3.5) across four windows:**

| Span | Net P&L | |
|---|---|---|
| **s1 (in-sample)** | **+$2,307** | ← the row visible at #3 on the dashboard |
| s2 | −$170 | |
| s3 | −$1,313 | |
| s4 | +$948 | |
| **Out-of-sample total** | **−$536** | |

*Analogy — a golfer's best hole:* the dashboard shows their finest shot from every round ever played, ranked. It says nothing about their average round — and the average round is what you would be paying for.

**Why this is a UI/labelling gap, not a data bug.** The leaderboard reports net P&L per run correctly. It just doesn't surface the three qualifiers that decide whether a number is meaningful: **(a)** in-sample vs out-of-sample, **(b)** whether the cost assumptions were realistic or zeroed, **(c)** how many configurations were searched before this one topped the list. A `cost-000` counterfactual currently sits next to a real run looking like its peer — visually identical, economically incomparable.

**Suggested improvement — ✅ IMPLEMENTED 2026-07-22 (PR #217).** The strategy list no longer defaults to a net-P&L ranking. Runs are grouped into the experiment family they came from, each header showing the **median and range** rather than the best; every row carries a **cost badge** (zero / reduced / modelled) and a **span badge**, both derived from config rather than from names, since an operator-typed name can lie and `taker_fee_pct = 0` cannot. Counterfactuals stay visible — striped and struck through — behind a **"realistic runs only"** toggle that collapses the 69 to **12**, of which **11 are losses**. P&L sort is still available, just no longer the default. Classification lives in one tested module, `ui/lib/strategyTaxonomy.ts`.

Three details only became clear once the real 69 were classified, and each one changed the design:

- **"Baseline" had to be a config fingerprint, not a name.** 24 of the 69 share the default name `Untitled strategy`; exactly one is the rank-#1 baseline — and that same config is *also* saved as `entry-sweep-3.0` and `sweep-exit-0.5`, all three landing on the identical $1,865.
- **In-sample vs out-of-sample had to be four-way, not binary.** Around 15 runs sit *inside or across* the 2026-03-01→06-23 tuning window (`Test A` 03-01→06-15, `6 months same data` 01-01→06-15). A "not exactly s1 ⇒ out-of-sample" rule would have stamped these with the green badge and laundered in-sample results as validation — a worse lie than the one being fixed. Anything overlapping the tuning window by less than 90% now reads **OVERLAPS IN-SAMPLE**.
- **Cost had to be three tiers.** `cost-002-s3` runs at 0.02/0.02 — neither free nor realistic, and untradeable either way.

**The one-line version:** *the dashboard shows the best results of a long search on a lucky window under friction-free assumptions; the analysis reports what happens on windows the strategy has never seen, paying real costs. Both are true — only the second one predicts your money.*

---

## 2026-07-24 — Why did the manual scan list shrink? (`MIN_LIQUIDITY_USD` raised to $1M)

**Q:** The manual/scan pair list got much shorter after the Phase-2 kickoff. What changed, and does the higher liquidity floor make the strategy more profitable?

**A:** Phase-2 Slice 0 raised the scan liquidity floor **`MIN_LIQUIDITY_USD` from `$10,000` → `$1,000,000`** 24h volume (`backend/config.py:188`, `.env.example`). Because the scan pairs every surviving market with every other, the candidate-pair count scales ≈ N²/2, so cutting the market count shrinks the hand-review list **super-linearly**: ≈ **179 markets / ~15,900 candidate pairs** at $10k → ≈ **48 markets / ~1,130 pairs** at $1M (survivor counts from `ohlcv_cache`, `docs/PHASE2_STRATEGY_PLAN.md` §5).

**Does it add edge? No.** This is a **tractability/executability** change (reason *ii* in the plan), not an alpha lever. The old $10k floor was effectively inert (179/179 cached HL markets already cleared it), so it thinned nothing; you were reviewing pairs in names you could not actually fill at size. The plan's "deciding experiment" (§4) **refuted** the raise-the-floor-for-edge hypothesis: the strategy's mid-price gross is *concentrated in the thinnest markets*, so filtering up **loses** money (gross +$2,554 → −$183 at ≥$100k/hr; net worse at every threshold). The names you drop carry no *tradeable* P&L. The floor only affects the **live scan (path a)** — it does **not** touch any backtest (backtest universe is `_universe()`, path b) and does **not** change `ENVIRONMENT` or push the bot toward going live. Tighten to $5M later only if the list stays unwieldy or fills disappoint.

---

## 2026-07-24 — Per-market cost model: why one backtest now charges different slippage per coin

**Q:** Phase-2 Slice 1 added a "per-market" cost model. What does it change, and does it make the strategy profitable?

**A:** Until now the backtest charged **one flat `slippage_pct`** on every fill — the same cost to cross BTC as to cross a dust alt. That's wrong in *both* directions: it overstates the cost of liquid names and **understates** the cost of thin ones. Since the strategy's gross P&L lives in the thinnest markets (§4 of `PHASE2_STRATEGY_PLAN.md`), the flat number flatters the result. Slice 1 adds `PER_MARKET_SLIPPAGE` (env flag, **default OFF**): when ON, each leg is charged its **market's half-spread**, resolved as override-table → **volume→spread curve** → measured-mean default (`backend/simulation/spread_cost.py`).

- **The curve** maps a market's mean hourly dollar-volume (`close×volume`) to a half-spread, calibrated to the measured distribution: `$1M/hr→0.0165%` (median), `$10k/hr→0.0615%` (P90), floored at `0.0086%` (liquid, P25), capped at `0.279%` (thinnest measured). On the live cache BTC (~$113M/hr) → `0.0086%`; a $2–4k/hr alt → ~`0.07%`.
- **Why a curve and not a per-coin table?** The 160-coin measurement that produced the aggregate percentiles was an ephemeral live-order-book snapshot and was **never persisted** — there's no per-coin table to seed from. The curve uses the per-market *volume* we do have (in `ohlcv_cache`) as a liquidity proxy; the override table is the extensible hook for real per-coin numbers as they're captured (operator decision 2026-07-24).

**Does it make the strategy profitable? No — and it's not meant to.** It's an **honesty** upgrade, not an alpha lever. Charging thin markets their real (wider) spread makes the very trades that generate the gross *more* expensive, so honest net can only move **down or sideways**, never up, versus the flat 0.05%. The path to a "yes" is unchanged (OOS net ≥ +$424, DSR-corrected, size-aware — §7). Scope: only the **walk-forward backtest** (the map is built once per run); real-time sim / fast-forward keep the flat cost; `ENVIRONMENT` and go-live are untouched.

**Confirmed empirically (2026-07-25, prod).** Re-running entry-3.5 s2–s4 at per-market cost gave OOS net **+$157** (vs the flat-real-taker +$187) — *below*, exactly as predicted. Still inside the ±$212 noise floor → statistically zero, NO-GO unchanged (`docs/strategy.md` Phase-2 campaign).

---

## 2026-07-25 — Does raising the backtest liquidity filter gain edge? (Slice 2)

**Q:** Phase-2 Slice 2 added a backtest universe liquidity/spread filter. If I turn it on and only trade the liquid names, does the strategy make more money?

**A: No. The evidence is decisive, and it's the opposite of intuition.** The filter (`BACKTEST_MIN_DOLLAR_VOLUME` / `BACKTEST_MAX_HALF_SPREAD_PCT`, both **default OFF**) prunes the backtest's market universe *before* the scan — drop markets below an hourly dollar-volume floor and/or above a half-spread ceiling. It exists to make the backtest **honest** (exclude untradeable dust, stress-test robustness), **not** to gain edge.

The Phase-2 §4 "deciding experiment" re-bucketed the OOS trades by liquidity and found the gross edge is **concentrated in the thinnest markets**:

| Both-legs floor | Trades | Gross | Net @ real taker |
|---|---|---|---|
| none (full) | 7,787 | **+$2,554** | +$187 (inside noise floor) |
| ≥ $100k/hr | 2,417 | −$183 | ≈ −$700 |
| ≥ $1M/hr | 823 | +$44 | ≈ −$130 |
| ≥ $5M/hr | 218 | +$98 | ≈ +$54 (218 trades — statistically zero) |

Because costs are **per-trade**, filtering up removes the (illiquid-driven) gross *faster* than it saves on cost — **net gets worse at every threshold tested**. So the operator's "raise the floor to cut noise and gain edge" hypothesis is **refuted**: liquidity is not an edge lever here. The productive reframe (`PHASE2_STRATEGY_PLAN.md` §5): the problem isn't "too much noise in the universe," it's "the gross edge is untradeable microstructure." The filter is shipped **off** and documented as an honesty/robustness knob so no one enables it expecting profit. (Note: this is the *backtest* universe, "path b" — entirely separate from the live-scan `MIN_LIQUIDITY_USD`, "path a", raised to $1M in Slice 0 for scan tractability.)

---

## 2026-07-25 — What is "market impact" and why does it make big trades worse? (Slice 3)

**Q:** Phase-2 Slice 3 added a "market impact" charge. What is it, and why does my backtest net get worse when I raise the per-leg size?

**A:** The half-spread is what you pay to cross the book *at top-of-book* (~$100). Trade **bigger** and your market order **walks the book** — filling at progressively worse levels. That extra cost is **market impact**, on top of the spread, and every cost figure before Slice 3 ignored it (they all assumed $100/leg). `MARKET_IMPACT=true` (env, **default OFF**, backtest-only) charges it per leg via the square-root law:

> `impact% = 100 · σ · √(Q / ADV)` — σ = market daily vol, Q = `usd_per_trade`, ADV = mean daily dollar-volume (`backend/simulation/market_impact.py`).

**Why bigger size hurts:** impact grows **∝ Q^1.5** while gross grows only **∝ Q**, so *per-dollar* returns fall as you scale up — bigger size **erodes** the edge, it doesn't multiply it. Validated on the live cache: a thin alt (~$29k/hr, σ≈5%) costs ≈**0.19%/leg at $1k** and ≈**0.42% at $5k** (matches `PHASE2_STRATEGY_PLAN.md` §4.3); BTC-class depth ≈0%. This is gate **B5** ("executable at real size") and it's an **honesty** charge, not an alpha lever — it can only make the honest net *worse* at real manual size. Combined with the strategy living in thin markets, it's the single most important reason the +$187/+$157 taker figure is *optimistic*: at real size the true net is lower still.

---

## 2026-07-25 — What does the "DSR" badge mean? (Slice 4 — multiple-testing correction)

**Q:** The strategy list has a new "DSR" badge. What is it, and does any config pass?

**A:** **DSR = Deflated Sharpe Ratio** (Bailey & López de Prado). The leaderboard shows the *best of a long search* — 69 configs were tried, so the top one is plausibly just the **luckiest draw**, not the most skillful. DSR asks the honest question: *given the observed Sharpe, how likely is the true Sharpe positive **after** correcting for how many configs were searched* (plus return non-normality and sample length)? It returns a probability in [0,1]:

- **`DSR 0.9x ✓` (green)** — ≥ **0.95**: survives the correction; significant at 5% *after* the search is accounted for. This is what **gate B3** requires.
- **`DSR 0.xx` (grey)** — < 0.95: after deflating for the 69-config search, indistinguishable from the luckiest draw. Not significant.

It's computed in-house (`backend/stats/deflated_sharpe.py`, stdlib only — no scipy/mlfinlab) and surfaced per row via `GET /api/backtest/significance`. **On today's evidence nothing clears it** — consistent with the standing NO-GO: the honest OOS nets (+$187 flat / +$157 per-market, both inside the ±$212 noise floor) are exactly the kind of result deflation flags as "could be luck." A companion **PBO** (Probability of Backtest Overfitting) is implemented and tested, but *not* shown on the leaderboard: PBO/CSCV needs configs measured over the *same* windows, and the saved configs span different date ranges — so it's kept as a tool for a controlled overfitting study, not a leaderboard badge. **Bottom line:** the dashboard now answers "would this survive the search?", not just "what did this run produce?".

---
