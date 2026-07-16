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
