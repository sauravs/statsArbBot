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
