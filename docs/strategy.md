# Strategy Tuning — Exit-|Z| Sweep & the profitable-config playbook

A focused, runnable recipe for tuning a **profitable Hyperliquid pairs backtest**,
anchored to the current best saved run (**"Untitled strategy rank #1", Net P&L
+$1,864.90 on $10k ≈ +18.6%**). It documents the **Exit-|Z| sweep** — a controlled
experiment to answer *"should trades wait longer before exiting?"* — with the
recommended values, **why** each value, and **what output to expect**.

> Companion docs: `docs/BACKTEST_PARAMETER_GUIDE.md` (empirical sweeps that actually
> return pairs/trades), `docs/TRADING_CONCEPTS.md` (the *why* behind the math), and
> the running Q&A in `docs/QA.md` (0G/MET exit-timing analysis, rank #1 P&L
> re-verification, cost model).

---

## 1. The recommended sweep

Create **three** strategies in the dashboard's **NEW STRATEGY** form that are
**identical except `Exit |Z|`**, then Run each. `Exit |Z|` is the *only* variable —
everything else is held fixed so the comparison is clean.

| Name | Entry \|Z\| | **Exit \|Z\|** | Stop \|Z\| | Z-window | Scan (d) | Trade (d) | Capital |
|---|---|---|---|---|---|---|---|
| `sweep-exit-0.5` | 3 | **0.5** | 4 | 21 | 21 | 7 | 10000 |
| `sweep-exit-0.3` | 3 | **0.3** | 4 | 21 | 21 | 7 | 10000 |
| `sweep-exit-0.1` | 3 | **0.1** | 4 | 21 | 21 | 7 | 10000 |

- Leave **Start/End blank** (same span as rank #1) and leave **Advanced** at its
  defaults. The only field that differs across the three rows is **Exit |Z|**.
- Run them **one at a time** — each is a heavy ~9k-trade Hyperliquid backtest, and
  back-to-back runs can strain the box's DB pool (issue #168/#170).
- Validation enforces `exit < entry < stop`, so `Exit 0.1 < Entry 3 < Stop 4` is
  fine (`backend/routers/backtest.py`).

---

## 2. Why these values (rationale per parameter)

| Param | Value | Why |
|---|---|---|
| **Entry \|Z\|** | **3** | Only opens on *extreme* dislocations, which revert more reliably → higher win-rate, fewer marginal trades bleeding costs. Sweeps show Entry 1.0 → 49% win / negative, Entry 2.0 → 72% win (`BACKTEST_PARAMETER_GUIDE.md:37-39`); rank #1 at 3 → 63% win **and positive** on real Hyperliquid data. |
| **Exit \|Z\|** | **0.5 / 0.3 / 0.1** | *The swept variable.* Exit closes when the spread has reverted to within `|z| < Exit` of its mean. **0.5** = take the reliable middle of the reversion (rank #1's setting); **lower = wait longer** for a fuller reversion (`z→0`). This is exactly the "should we wait more?" lever (`backend/statcore/signals.py:138`). |
| **Stop \|Z\|** | **4** | Hard breakdown stop: if `|z|` diverges past 4 the cointegration is likely broken — cut the loss. |
| **Z-window** | **21** | Rolling lookback (bars) for the z-score mean/std. Shorter = jumpier/exits sooner; longer = smoother. 21 is the project default. |
| **Scan (formation)** | **21d** | Short formation window **aligns more markets** on crypto (the scan drops any market missing a bar), so more candidate pairs (`BACKTEST_PARAMETER_GUIDE.md:56-64`), without being so short the fit is spurious. |
| **Trade (test)** | **7d** | Short hold **caps funding** (funding accrues hourly, long pays/short receives) and forces frequent **re-scans**, so you always trade *currently* cointegrated pairs. Long holds erode a thin edge (see 0G/IP −$0.12 @ 14h vs 0G/MET +$1.70 @ 5h in `docs/QA.md`). |
| **Capital** | **10000** | Baseline; P&L is reported in $ and as final capital. Per-trade notional defaults to `USD_PER_TRADE=$100` (`config.py:112`). |

**Fixed cost model (defaults, real data):** taker fee **0.05%/leg/fill** (4 fills a
round trip), slippage **0.05%/leg/fill** (adverse), funding at the **real hourly
rate** (long pays / short receives). `net = gross − fees + funding`
(`backend/simulation/costs.py`). Every winning trade must clear this round-trip cost.

---

## 3. Output expectation

- **`sweep-exit-0.5` should ≈ reproduce rank #1 (+$1,864.90).** That's the sanity
  check that the clone is faithful; small differences are fine if the global config
  drifted since rank #1 was first run.
- **If Net P&L rises 0.5 → 0.3 → 0.1:** waiting longer *does* pay across the whole
  strategy — the extra convergence captured on winners like 0G/MET outweighs the
  costs. Consider adopting a tighter exit.
- **If Net P&L falls 0.5 → 0.3 → 0.1:** the extra **funding** from longer holds, plus
  the trades that **stall or re-diverge** (and exit on the time-stop / window-end
  instead of a clean take-profit), outweigh the winners. The original 0.5 was right;
  0G/MET was survivorship bias.
- **Also watch, not just Net P&L:**
  - **Win rate** — likely *drops* as the exit tightens (some trades never reach the
    stricter `|z|` target → they close on the time-stop/window-end).
  - **Average hold time** — *rises* as the exit tightens (more funding exposure).
  - **Exit-reason mix** — the **Reverted** share should fall and **Time-stop /
    Window-end** rise as Exit |Z| tightens; that's the mechanism to look for.
  - **Equity-curve shape** — prefer smooth up-and-to-the-right over a jagged line
    that merely ends higher.

**Prior hypothesis (WRONG — kept for honesty):** a shallow optimum was expected —
0.3 edging out 0.5, with 0.1 giving gains back to funding + missed targets.

**Intermediate 3-point result (2026-07-16) — later shown to be a sampling artifact:**
Exit 0.5 → 0.3 → 0.1 gave $1,864.90 → $2,144.79 → $2,485.15, a clean monotone
"+33% by tightening." It looked real; it wasn't.

**Final finer result (2026-07-19, 6 points, this same span) — the exit is a NOISE
lever, not a profit lever:**

| Exit \|Z\| | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| 0.05 | $2,127 | 58.7% | 7,541 | 12.40% |
| 0.10 | $2,485 *(spike)* | 60.9% | 8,231 | 11.93% |
| 0.15 | $2,051 | 61.6% | 8,608 | 11.37% |
| 0.20 | $1,850 *(worst, below baseline)* | 62.3% | 8,829 | 11.57% |
| 0.30 | $2,145 | 63.0% | 9,161 | 11.42% |
| 0.50 | $1,865 | 63.2% | 9,439 | 12.70% |

- **Real & smooth:** win rate rises as the exit loosens (58.7 → 63.2%), trade count
  rises (7.5k → 9.4k), and **drawdown is flat (~11–13%)** — mechanical, monotone.
- **Noise:** net P&L is jagged ($2,087 ± $212, 1σ). The best (0.1, +1.9σ) and worst
  (0.2, −1.1σ, *below* the do-nothing baseline) are neighbors. On **one span**, a lone
  2σ bump is what noise looks like, not an optimum.

**Recommendation (updated):** **do not retune the exit off this** — keep 0.5 (or 0.3;
the gap is inside the noise), don't ship 0.1. The exit is a weak lever; hunt the edge
elsewhere (entry threshold, pair-quality/p-value, half-life, trade window, costs).
**Method lesson:** a coarse sweep can fabricate a trend — sample finely, and re-validate
across multiple spans, before trusting a single-point optimum. Full write-up +
analogy in `docs/QA.md` (2026-07-19 finer-sweep entry).

---

## 4. How to read the result

When all three are COMPLETED, compare side by side:

| | Net P&L | Win rate | Trades | Avg hold | Reverted % | Time-stop/Window-end % |
|---|---|---|---|---|---|---|
| exit 0.5 | | | | | | |
| exit 0.3 | | | | | | |
| exit 0.1 | | | | | | |

Pick the exit that **maximizes Net P&L with a still-healthy curve and exit mix** —
not just the highest final number. Then **re-validate on a different date span**
before trusting it (a config that only wins on one window is curve-fit;
`docs/TRADING_CONCEPTS.md` Part 6).

> ⚠️ Reality check: `BACKTEST_PARAMETER_GUIDE.md:80-83` found naive crypto pairs are
> usually **net-negative after costs**. rank #1's +18.6% is one Hyperliquid span and
> should survive out-of-sample re-runs (and eventually testnet) before it's trusted
> live — backtests assume clean fills; live slippage is worse.
