# Backtest Parameter Guide — why "no cointegrated pairs / no trades", and what to use

_Empirically derived 2026-06-05 by sweeping the actual engine over both data sources._

## TL;DR — the #1 cause of "0 pairs / 0 trades"

**The backtest does not read the data shown in the coverage banner when the stack
is in `fake` mode.** The data source is switched by `SCAN_DATA_SOURCE`:

| `SCAN_DATA_SOURCE` | What the backtest actually replays | Span | Markets |
|--------------------|------------------------------------|------|---------|
| `fake` (DEMO) | Synthetic **DEMO** series (`exchanges/demo.py`) | **2024-01-01 → 2026-06-03** (≈21k hourly bars; #96) | DEMO1–4, NOISE1–2 |
| `dydx` (LIVE) | The cached dYdX history (`OhlcvCache`) | 2024-01-01 → 2026-06-03 | 38 markets |

> The Backtest page shows a **DEMO/LIVE** badge (#92) — switch it to pick the source.

_Historical note:_ the original failure was that the DEMO series spanned only
~16 days (2025-01-01 → 2025-01-17), so real-calendar dates loaded 0 bars → 0
trades. **Fixed in #96** — DEMO now spans 2024-01-01 → 2026-06-03, so any normal
date range / window finds pairs and trades (see §A). Always check the DEMO/LIVE
badge so you know which source you're running.

---

## A. Offline / DEMO mode (`fake`)

The demo data now spans the **same range as the real cache** (2024-01-01 →
2026-06-03; #96) with two genuinely cointegrated pairs by construction
(DEMO1/DEMO2, DEMO3/DEMO4, both p < 0.001) persisting throughout — so **normal
params just work**, like LIVE. Leaving Start/End **blank** runs a quick recent
window; explicit dates anywhere in the span are fine.

Empirically validated (full engine, DEMO, dates 2024-05 → 2026-07):

| Entry | Exit | Stop | p-value | half-life | scan/trade | trades | win% | net |
|------:|-----:|-----:|--------:|----------:|-----------:|-------:|-----:|----:|
| **1.5** | 0.5 | 4 | 0.05 | 72h | **90d / 30d** | 4,486 | 63% | **+\$405.79** |
| 2.0 | 0.5 | 4 | 0.05 | 72h | 90d / 30d | 1,990 | 72% | +\$335.34 |
| 1.0 | 0.5 | 4 | 0.05 | 72h | 90d / 30d | 7,621 | 49% | −\$3.41 |

**Recommended demo preset:** Entry 1.5 / Exit 0.5 / Stop 4, p≤0.05, half-life≤72h,
Z-window 21 — any normal scan/trade windows and date range in the span.

---

## B. Real dYdX data (`SCAN_DATA_SOURCE=dydx`)

Switch the stack/data-source toggle to `dydx` first, otherwise the dates below do
nothing (see TL;DR). Two realities of real crypto perps:

1. **Cointegration is rare.** Over a 90-day window, `p≤0.05` yielded **0** pairs;
   `p≤0.10` → 1; `p≤0.20` → 7. Crypto is dominated by one BTC factor, so genuine
   pairwise cointegration is scarce and unstable. **Use p≤0.10–0.20.**
2. **Data completeness decimates the universe.** The scan drops any market missing
   a single bar in the window (`dropna(how="any")`). Aligned-market count:

   | scan window | aligned markets (of 38) |
   |------------:|------------------------:|
   | 14d | 17 |
   | 30d | 12 |
   | 45d | 9 |
   | 90d | 6 |

   → **shorter scan windows align more markets** (more candidate pairs), and
   **earlier-2024 / early-2025 spans** are denser than late-2025+.

Empirically validated (full engine, span 2024-02-01 → 2024-12-01):

| Entry | Exit | Stop | p-value | half-life | scan/trade | pairsΣ | trades | win% | net |
|------:|-----:|-----:|--------:|----------:|-----------:|-------:|-------:|-----:|----:|
| **1.0** | 0.5 | 4 | **0.10** | **168h** | **30d / 15d** | 98 | 2684 | 55% | −\$727 |
| 1.0 | 0.5 | 4 | 0.20 | 168h | 30d / 15d | 98 | 2684 | 55% | −\$727 |
| 1.5 | 0.5 | 4 | 0.20 | 336h | 45d / 21d | 85 | 2324 | 57% | −\$836 |
| 1.0 | 0.5 | 4 | 0.20 | 336h | 21d / 10d | 216 | 3949 | 53% | −\$1885 |

**Recommended real-data preset (to GET pairs + trades):** Entry 1.0–1.5 /
Exit 0.5 / Stop 4, **p≤0.10**, **half-life≤168h**, Z-window 21, **scan 30d /
trade 15d**, dates inside **2024-02-01 → 2024-12-01** (or another dense span).

> Note: all real-data configs are **net-negative** — naive cointegration pairs
> trading on crypto perps bleeds to fees + funding. Finding pairs/trades is solved
> by the above; *profitability* is a separate selection/tuning problem (tighter
> pair quality, fewer concurrent pairs, lower costs, funding-aware sizing).

---

## C. "Popular" quant ranges (reference)

| Param | Typical | Effect |
|-------|---------|--------|
| Entry \|Z\| | 1.5–2.0 (1.0 to trade more) | divergence to open |
| Exit \|Z\| | 0.0–0.5 | take-profit on reversion |
| Stop \|Z\| | 3.0–4.0 | breakdown stop |
| Z-window | 20–60 bars | z-score lookback |
| p-value | 0.05 standard; **0.10–0.20 for crypto** | cointegration cutoff |
| half-life | ≤72h default; **≤168h for crypto** | max mean-reversion speed |
| scan window | 60–120d (clean data); **shorter aligns more crypto markets** | formation |
| trade window | 30–180d | out-of-sample hold |

---

## D. Known limitations surfaced by this investigation

1. **The coverage banner (#88) shows the real-cache span even in `fake` mode**, so
   it invites operators to pick dates the engine can't use offline. The banner
   should reflect the **active** data source (the demo span in fake mode).
2. **No feedback when chosen dates fall outside the usable span** — the run simply
   completes with 0 bars. A pre-run hint ("dates outside available data") would help.
3. **`dropna(how="any")` per window** drops a whole market for one missing bar,
   shrinking the real-data universe drastically. Worth revisiting (e.g. tolerate a
   small gap %, or forward-fill).
