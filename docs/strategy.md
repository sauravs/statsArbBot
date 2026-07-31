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

---

## Entry |Z| — THE real lever (2026-07-19)

Where the exit was noise, the **entry threshold is the dominant lever**. Sweep on
Hyperliquid (all else = rank #1, one span):

| Entry \|Z\| | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| 1.5 | -$5,021 | 60.0% | 18,240 | 51.1% |
| 2.0 | -$5,316 | 59.4% | 15,842 | 53.2% |
| 2.5 | -$5,640 | 60.5% | 13,269 | 62.3% |
| 3.0 | +$1,865 | 63.2% | 9,439 | 12.7% |
| 3.5 | **+$2,307** | **66.1%** | 2,940 | **8.9%** |

- **Be ruthlessly selective.** Only |z|>=3 dislocations are profitable; below that the
  strategy loses ~$5k **and** suffers **50-62% drawdowns** (ruinous). 3.5 beats 3.0 on
  return, win rate, AND drawdown — so it is a **real regime**, not an overfit spike
  (swing is ~37sigma vs the exit noise floor).
- **Set entry high: 3.0-3.5.** Never <= 2.5. (Exit: keep 0.5. Stop: keep 4, weak lever.)
- Analogy: *wait for the fat pitch* — swing only at the rare perfect pitch (entry 3.5),
  not every pitch (entry 1.5). The mediocre 2.5-3.0 band is where you strike out.
- Caveat: one span; re-validate 3.0 vs 3.5 across other date ranges, and note 3.5's
  thin trade count (2,940). Full write-up in `docs/QA.md` (2026-07-19 entry-sweep).

### Entry |Z| — but selectivity has a CEILING: net P&L peaks at 3.5 (2026-07-19)

Pushing the entry bar *higher* (3.5 / 3.75 / 4.0, all else = rank #1) answers "does more
selectivity keep paying?" — **no.** Net P&L is single-peaked at **3.5**, then falls, even
as every per-trade quality metric keeps improving:

| Entry \|Z\| | Net P&L | Win % | Trades | Avg $/trade | Max DD |
|---|---|---|---|---|---|
| 3.0 | +$1,865 | 63.2% | 9,439 | $0.198 | 12.7% |
| **3.5** | **+$2,307** | 66.1% | 2,940 | $0.785 | 8.9% |
| 3.75 | +$1,916 | 63.9% | 1,209 | $1.585 | 3.88% |
| 4.0 | +$1,020 | 84.0% | 387 | $2.635 | 2.36% |

- **Mechanism (`net = trades × avg $/trade`):** per-trade quality rises monotonically
  ($0.20→$2.64) and drawdown/win-rate improve, **but trade count collapses faster**
  (9,439→387). Past ~3.5 the volume loss overtakes the quality gain, so total P&L erodes.
  The crossover — where raising the bar stops helping — is right at **3.5**.
- **4.0's 84% win rate is a vanity metric:** 387 trades made only $1,020 (< half of 3.5).
  Win rate up, dollars down; 387 bets is too thin to trust (its 2.36% DD just means it
  barely traded, not that it's safe).
- **Use entry 3.5** (peak: best net, 66% win, 8.9% DD, still 2,940 trades). **3.0** = robust
  fallback (3× trades). **Never push above 3.5** — it starves the strategy. Entry hunt done.
- Analogy: *the batter who almost never swings.* 3.5 = swing at every fat pitch (drives in
  the most runs). 4.0 = so picky he swings once a game — 84% are hits, but he scores fewer
  runs because he's barely at the plate. Precision ≠ productivity; there's a discipline
  sweet spot. Full write-up in `docs/QA.md` (2026-07-19 entry high-sweep).
- (4.0 used Stop 5 to avoid the degenerate entry==stop; Stop is a weak lever, so it doesn't
  confound the comparison.) Next lever = **pair quality (p-value / half-life)**, not entry.

### Pair quality (p-value) — keep the cointegration gate TIGHT (0.01) (2026-07-20)

Sweeping `pvalue_max` (0.05 / 0.10 / 0.15, all else = rank #1 / entry 3.0 / base p-value 0.01):

| p-value | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|
| **0.01** (baseline) | **+$1,865** | 63.2% | 9,439 | 12.7% |
| 0.05 | −$1,176 | 61.6% | 15,208 | 24.19% |
| 0.10 | −$1,176 | 61.6% | 15,208 | 24.19% |
| 0.15 | −$1,176 | 61.6% | 15,208 | 24.19% |

- **Tight wins, decisively.** Loosening 0.01→0.05 flips +$1,865 → −$1,176 (~$3k swing), adds
  +61% trades (junk pairs), doubles drawdown (12.7→24.2%). Weakly-cointegrated pairs don't
  revert — they wander into stops. p-value is a **dominant quality lever; be selective.**
- **Saturates at 0.05:** 0.05/0.10/0.15 are identical to the cent. A pair needs
  `p < pvalue_max` **AND** `t_stat < 5% critical value` (`statcore/cointegration.py:59`); that
  second gate is a hard-wired 95%-confidence floor the dial can't loosen. So `pvalue_max` only
  bites when set *below* 0.05 (0.01 = demand ~99% confidence). Keep it at **0.01**.
- Analogy: *two bouncers.* #2 is permanent (admits 95%-confident pairs); #1 is the dial. Set #1
  to 0.01 and he demands 99% — turning away the borderline tethers that snap and cost $3k.
  Loosen #1 past 0.05 and nothing changes — #2 already turned everyone else away.
- **Two selectivity axes, same lesson:** entry |Z| (when to trade) → 3.5; p-value (which pairs
  allowed) → 0.01. Both punish permissiveness; the edge is the small high-conviction set.
  Candidate best config = **entry 3.5 + p-value 0.01 + exit 0.5 + stop 4.** Half-life
  (`max_half_life_h`, base 72h) is the last un-swept pair-quality lever. Full write-up in
  `docs/QA.md` (2026-07-20 p-value sweep).

### ⚠️ Multi-span re-validation: entry 3.5 is CURVE-FIT — do NOT trust live (2026-07-20)

Ran the candidate best config (entry 3.5 + pval 0.01 + exit 0.5 + stop 4) on 3 **other** spans:

| Span | Window | Net P&L | Win % | Trades | Max DD |
|---|---|---|---|---|---|
| **s1** (in-sample) | 2026-03→06 | **+$2,307** | 66.1% | 2,940 | 8.9% |
| s2 | 2025-11→2026-03 | −$170 | 66.1% | 3,593 | 17.57% |
| s3 | 2025-07→11 | −$1,313 | 61.9% | 2,652 | 22.35% |
| s4 | 2025-03→07 | +$948 | 63.0% | 1,499 | 6.98% |

- **Out-of-sample (s2+s3+s4) = −$536 net.** The +$2,307 was the best of four noisy draws,
  picked *because* it topped this window (selection bias). It does **not** generalize.
- **Robust:** win rate (62–66% every span) — selectivity reliably wins ~2/3 of trades and
  prevents the 50–62% drawdowns of permissive configs. **Not robust:** the dollar edge — on
  losing spans avg loss > avg win (fat left tail: pairs break cointegration, run to the stop).
- **Verdict:** the selectivity levers (entry ≥3, pval 0.01) are **necessary but not
  sufficient** — they buy *survival*, not *profit*. **Do not trust entry 3.5 / rank #1 live.**
- Analogy: *win-loss record vs point differential.* Wins 63% of games (by a point), loses 37%
  (by ten) — good record, negative differential. A winning season (s1) doesn't make a good team.
- Next: (1) test **entry 3.0** OOS (more trades → steadier?); (2) attack the left tail (tighter
  half-life / z-stop / mid-trade coint re-check). Full write-up in `docs/QA.md` (2026-07-20 re-validation).

### Entry 3.0 OOS: strictly worse than 3.5 — selectivity confirmed, family still OOS-negative (2026-07-20)

Re-ran entry 3.0 on the same 3 OOS spans (diversification hypothesis test):

| Span | entry 3.0 (net / DD) | entry 3.5 (net / DD) |
|---|---|---|
| s1 (in-sample) | +$1,865 / 12.7% | +$2,307 / 8.9% |
| s2 | −$1,289 / 37.68% | −$170 / 17.57% |
| s3 | −$3,334 / 41.54% | −$1,313 / 22.35% |
| s4 | −$822 / 14.76% | +$948 / 6.98% |
| **OOS sum** | **−$5,445** | **−$536** |

- **Diversification hypothesis REJECTED.** 3.0 is strictly worse than 3.5 on *every* span, both
  axes. 3-for-3 negative OOS with 38–42% drawdowns — the extra ~8k trades/span are marginal
  |z| 3–3.5 signals that amplify the left tail, not smooth it.
- **Selectivity CONFIRMED robust** (the generalizable half of the entry finding): more selective
  = higher net AND lower DD, on all 4 spans. "Never lower the entry bar" holds decisively.
- **But no entry threshold is OOS-profitable.** The deficit is structural (left tail: pairs break
  cointegration → run to stop), not a tuning knob. Only structural levers remain: tighten
  **max_half_life_h** (72h→24/48h) or the z-stop. Full write-up in `docs/QA.md` (2026-07-20 entry-3.0 OOS).

### 🔚 Left-tail attack: half-life & z-stop are non-levers — EVERY parameter exhausted (2026-07-21)

Final step, on **s3** (worst OOS span, entry 3.5 baseline = −$1,313 / 22.35% DD):

| `max_half_life_h` | Net | Trades | Max DD | | `stop_threshold` | Net | Max DD |
|---|---|---|---|---|---|---|---|
| 72h (base) | −$1,313 | 2,652 | 22.35% | | 3.75 (tight) | −$1,664 | 20.62% |
| 48h | −$1,326 | 2,636 | 22.40% | | 4.0 (base) | −$1,313 | 22.35% |
| 24h | −$1,348 | 2,551 | 22.88% | | 6.0 (wide) | −$1,290 | 24.28% |

- **Half-life = NON-BINDING (inert).** A 24h cap removes only ~4% of trades and leaves drawdown
  flat — admitted pairs already revert in <24h. **So the OOS losses are NOT slow-reverting pairs**;
  the losers revert fast but a subset *breaks* (cointegration fails), which no formation-window
  statistic can predict. (Analogy: *a thermostat in a house with no heater.*)
- **Z-stop = pure RISK/RETURN TRADE-OFF.** Wider = better net but worse DD, in lockstep; no setting
  improves both, best net beats base by $23 (noise). The **tight** stop is *worse* on net —
  refuting "losers run to the stop": trades dipping to 3.75 mostly come back, so a tight leash just
  books would-be reverters as losses. (Analogy: *a see-saw — you tilt it, you never lift it.*)

**COMPLETE LEVER TAXONOMY — none creates an out-of-sample edge:**

| Lever | Behaviour | OOS edge? |
|---|---|---|
| Exit \|Z\| | noise | No |
| Entry \|Z\| | potent; selectivity robust (3.5>3.0 all spans) | No — OOS-negative at every value |
| p-value | potent below 0.05; saturates above | No — prevents ruin, not profit |
| Half-life | non-binding / inert | No |
| Stop \|Z\| | risk/return trade-off | No |

**VERDICT (⚠️ SUPERSEDED — see the cost decomposition below):** *"naive Hyperliquid stat-arb 2025–26
is breakeven-to-negative after costs; live deployment is NOT justified."* This was right about the
**net** result but wrong about the **cause** — it assumed the signal was dead. The cost decomposition
below shows the signal is fine and **friction** is the whole problem. Kept for honesty. Full write-up
in `docs/QA.md` (2026-07-21 left-tail attack).

### ✅ COST DECOMPOSITION — the conclusion REVERSES: real gross edge, destroyed by friction (2026-07-21)

Re-ran entry 3.5 on the OOS spans with `taker_fee_pct`/`slippage_pct` = 0.02 and 0.00:

| Span | Net (actual) | **Gross (measured)** | Friction | Max DD: net → gross |
|---|---|---|---|---|
| s2 | −$170 | **+$1,181** (69.1% win) | $1,352 | 17.57% → **10.14%** |
| s3 | −$1,313 | −$200 (66.4% win) | $1,113 | 22.35% → **14.48%** |
| s4 | +$948 | **+$1,573** (68.5% win) | $626 | 6.98% → **5.64%** |
| **OOS** | **−$536** | **+$2,554** | **$3,090** | — |

- **Identity closes exactly** ($2,554 − $3,090 = −$536 ✓). Friction ≈ **$0.398/trade** (consistent
  across spans: 0.375 / 0.416 / 0.417). Cost model is **exactly linear** (s3: 0.00→−$200,
  0.02→−$648, 0.05→−$1,313; s4 gross predicted +$1,574 vs actual +$1,573.47).
- **The signal is NOT dead.** Positive OOS gross edge, 3 of 4 spans strongly positive, 66–69% win
  rates, and *good* drawdowns once friction is removed (5.6–14.5%). The earlier verdict
  over-generalised from s3 — the one flat span.
- **Break-even needs only a ~17% cost cut:** OOS turns positive below **0.0413%** per side.
  At 0.02% → **+$1,318**; at 0.01% (maker fills) → **+$1,936**; at 0.00% → +$2,554.
- **"Selectivity" was largely a FRICTION artifact.** Friction is a fixed ~$0.40/trade tax, so it
  kills low-edge-per-trade configs. Gross totals on s1: entry 3.0 = **+$5,612**, 3.5 = +$3,474,
  3.75 = +$2,396, 4.0 = +$1,174 — **at zero cost entry 3.0 is the BEST, not the worst** (OOS too:
  3.0 gross ≈ +$4,668 vs 3.5's +$2,554). 3.0 only looked catastrophic because it pays 3× the
  friction. **Optimal entry is a function of the cost level** (3.0 overtakes 3.5 below ~0.015%/side).
- Analogy: *a toll road.* Every trade pays the same ~$0.40 toll. Short trips (|z|≈3, ~$0.60 gross)
  barely clear it; long trips (|z|≥4, ~$3) clear it easily. Raising the entry bar was just refusing
  short trips because the toll ate them — sensible at a high toll, but it forgoes many genuinely
  profitable journeys. **Lower the toll and the whole network is worth driving.**

**CAVEATS (not a free lunch):** zero-cost is a *counterfactual upper bound*, not a runnable config;
maker orders don't guarantee fills (**legging risk** on a 2-legged trade, unmodelled); passive fills
are **adverse-selected** (lowering `slippage_pct` does NOT capture this); entry-3.0 gross figures are
*derived* from the friction constant, not directly measured. Funding **is** included in gross.

**CORRECTED ROADMAP — execution, not parameters:** (1) get Hyperliquid's real maker/taker schedule;
(2) validate the 0.05% slippage assumption against real fills; (3) directly measure entry 3.0 at low
cost, re-derive the cost-dependent optimal entry; (4) model maker execution *honestly* (fill
probability, adverse selection, legging risk) — this decides whether the edge is harvestable;
(5) only then reconsider live. **"Real gross edge" ≠ "profitable after realistic execution."**
Full write-up in `docs/QA.md` (2026-07-21 cost decomposition). **Steps 1–3 are now DONE — see below.**

### 💰 Execution economics: real fees + MEASURED slippage (2026-07-22)

> ⚠️ **OPERATOR CONSTRAINT — read this first.** The operator will trade signals **manually with
> MARKET orders only** (pick a trade off the manual-trading screen after a re-scan, execute at
> whatever price the exchange gives). **There will be no limit/maker orders and no automated
> execution.** So the **taker row below is the operative one (+$187 = statistically zero)**; the
> maker rows are analytically interesting but **unavailable**. The maker-modelling work (fill
> probability / adverse selection / legging risk) is **dropped**. See the roadmap at the end of
> this section.

**Real Hyperliquid fees (base tier): taker 0.045%, maker 0.015%** (tiers fall to 0.028%/0.000% at
>$500M; staking discounts 5–40%). **Measured slippage: trade-weighted half-spread = 0.0316%**
(160 coins, 97% leg-fill coverage; median 0.0165%, P90 0.0615%, max 0.279%). Both our modelled
0.05% fee *and* 0.05% slippage were pessimistic.

**Measured gross by entry (OOS, zero-cost runs):**

| Config | Gross | Friction @0.10% | Break-even rate | Zero-cost DD (s2/s3/s4) |
|---|---|---|---|---|
| entry 3.5 | +$2,554 | $3,090 | **0.0827%** | 10.1 / 14.5 / 5.6% |
| entry 3.0 | **+$4,379** | $9,825 | **0.0446%** | 26.6 / 22.3 / 8.7% |

**Net by execution regime:**

| Regime | Total/fill | entry 3.5 | entry 3.0 |
|---|---|---|---|
| Model (0.05+0.05) | 0.100% | −$536 | −$5,446 |
| **Real taker** (0.045+0.0316) | 0.0766% | **+$187** | −$3,147 |
| Taker +15% staking | 0.0699% | +$394 | −$2,489 |
| **Maker + full half-spread** (0.015+0.0316) | 0.0466% | **+$1,114** | −$199 |
| Maker, no spread cost (0.015+0) | 0.015% | +$2,091 | **+$2,905** |

- **Taker is NOT a business:** +$187 sits inside the ±$212 noise floor — statistically zero.
- **Maker is where the edge lives:** +$1,114 even charging adverse selection at the *full*
  half-spread. Taker→maker is worth ~**$1,900 OOS**, ~4× the entire net deficit.
- **entry 3.5 stays the right config.** Entry 3.0 has 1.71× the gross (confirming the friction-artifact
  thesis) but 3.2× the friction and ~2× the drawdown; it only overtakes 3.5 below **0.0271%/fill**
  (near-perfect execution) and is still *negative* at realistic maker levels. "Selectivity was a
  friction artifact" holds for the **gross** ranking; the **practical** ranking still favours 3.5.
- **Cheap win found:** slippage dispersion is wide (P90 0.0615%, worst 0.279%) and the scan admits
  any cointegrated pair regardless of tradability. **Add a spread/liquidity filter** (exclude
  >0.06% half-spread markets) — targeted, cheap, likely a direct improvement.

**CAVEATS:** spreads are a *current* snapshot, not historical — and the strategy enters at extreme
dislocations when spreads *widen*, so the taker case is optimistic. **Maker fill probability and
legging risk remain unmodelled** — the biggest unknown. Adverse selection charged as a flat
half-spread is a crude proxy.

**NEXT — CORRECTED for market-order-only manual trading:**
- ~~model maker execution honestly~~ **DROPPED** — irrelevant; the operator always crosses the spread.
  Note the backtest **already models market orders correctly**: `taker_fee_pct` is charged on every
  leg at entry+exit and `apply_slippage()` fills adversely (BUY above / SELL below,
  `backend/simulation/costs.py:49-51`). There is **no maker/limit assumption anywhere in the model**,
  so no modelling gap exists for the operator's intended execution.
- **(1) Add a liquidity/spread filter to the backtest universe — now THE deciding experiment.**
  `_universe()` (`backend/backtest/engine.py:604-606`) returns *all* available markets with no
  liquidity filter, so this needs a small code change. Slippage by tier: P25 **0.0086%**, median
  **0.0165%**, mean **0.0316%** → holding gross constant, OOS would be **+$898 / +$654 / +$187**.
  **Caveat: narrowing the universe also shrinks gross** (fewer pairs → fewer trades), so the net
  effect is genuinely uncertain and must be *measured*, not extrapolated.
- **(2) Add a market-impact estimate.** The measured half-spread assumes **$100/leg** at
  top-of-book. Manual size will be far larger, and in thin alt perps book-walking could dominate
  every cost measured so far.
- **(3) Sample spreads in volatile periods** — entries happen at extreme dislocations when spreads
  widen, so the taker case above is optimistic.
- **(4) Live remains unjustified**: on market orders the strategy is currently **+$187 OOS,
  inside the ±$212 noise floor**. Only (1) could change that. Full write-up in `docs/QA.md`
  (2026-07-22 execution economics + market-order correction).

---

## Phase-2 campaign — honest measurement machinery (2026-07-24 →)

Standing verdict unchanged: **NO-GO for live trading.** Phase-2 does **not** ship a
strategy; it builds the measurement + selection machinery so any future edge can be
proven or ruled out cheaply (`docs/PHASE2_STRATEGY_PLAN.md` §7). One gated PR per slice.

- **Slice 0 — `MIN_LIQUIDITY_USD` $10k → $1M** (live scan, path a). Tractability, not
  alpha; no backtest/trading/`ENVIRONMENT` change. Shipped + deployed to prod.
- **Slice 1 — per-market realistic cost model.** `PER_MARKET_SLIPPAGE` (default OFF)
  replaces the flat `slippage_pct` with a per-market half-spread charged per leg:
  override table → **volume→spread curve** (calibrated to the measured percentiles:
  liquid→0.0086%, median 0.0165% @ $1M/hr, P90 0.0615% @ $10k/hr, cap 0.279%) →
  measured-mean default. Backtest-only; sim/FF stay flat. Honest cost, **not** alpha —
  charging thin markets their real (wider) spread can only move honest net **down or
  sideways** vs the flat 0.05%, never up. `backend/simulation/spread_cost.py`;
  see `docs/BACKTEST_PARAMETER_GUIDE.md` §C2 and the 2026-07-24 `docs/QA.md` entry.

  **Attribution re-run (2026-07-25, prod, `PER_MARKET_SLIPPAGE=on`).** Fresh entry-3.5
  OOS sweeps cloning the exact cost-000 config (spans/params), now charging real taker
  fee (0.045%) + **per-market** slippage. Ran on prod (deep 2024+ HL history is
  prod-only). Rows `per-market-3.5-s2/s3/s4`
  (`cmrz6qpb10001wulpxmllt6to` / `cmrz6qpd10002wulpuujuiate` / `cmrz6qpfq0003wulpdv53iw1n`):

  | Span | Trades | Win% | Net (per-market) |
  |---|---|---|---|
  | s2 (2025-11-07→2026-03-01) | 3,595 | 66.8% | **+$73.80** |
  | s3 (2025-07-16→2025-11-07) | 2,657 | 62.8% | **−$1,030.32** |
  | s4 (2025-03-24→2025-07-16) | 1,500 | 64.7% | **+$1,113.74** |
  | **OOS total** | **7,752** | **~65%** | **+$157.22** |

  **Read (attribution only — spread-only, NOT a new verdict).** Gross reconstructs to
  ≈ **+$2,553** (matches the +$2,554 zero-cost figure) at **~$0.31/trade** per-market
  friction. Per-market net **+$157** lands **just below** the documented flat-real-taker
  **+$187** — exactly the model's prediction: the trades cluster in thin markets that pay
  **wider-than-mean** spreads, so honest cost moves net **down** (~$30), never up. It
  remains **well inside the ±$212 noise floor → statistically zero. NO-GO unchanged.**
  This figure is still **pre-impact** (assumes $100/leg top-of-book) and **pre-DSR**, so
  it stays *optimistic*; the definitive honest number lands after Slice 3 (market impact)
  + Slice 4 (deflated-Sharpe correction). A same-engine flat control (flag off) was not
  run — both land at "zero", so it would not change any decision.

- **Slice 2 — backtest universe liquidity/spread filter (path b).** Optional,
  **default-OFF** knobs (`BACKTEST_MIN_DOLLAR_VOLUME` $/hr floor,
  `BACKTEST_MAX_HALF_SPREAD_PCT` ceiling) that prune the backtest universe *before*
  the scan, reusing the Slice-1 `get_dollar_volumes` + `spread_cost`. Shipped **with
  the §4 refutation documented**: this is the engine change the plan calls the
  "deciding experiment," and it is an **honesty/robustness** knob, **not** an alpha
  lever. The evidence is decisive — gross is concentrated in the thinnest markets, so
  filtering up **loses** money (gross +$2,554 → −$183 @ ≥$100k/hr; net worse at every
  threshold). Do **not** enable it expecting profit. Live-cache survivor counts (avg
  over cached bars): 179 → 74 (≥$40k/hr) → 7 (≥$1M/hr); half-spread ≤0.05% → 85, ≤0.02%
  → 10. `backend/simulation/spread_cost.py::filter_universe`; see
  `docs/BACKTEST_PARAMETER_GUIDE.md` §C3 and the 2026-07-25 `docs/QA.md` entry.
  Distinct from Slice 0's `MIN_LIQUIDITY_USD` (that's the live scan, path a).

- **Slice 3 — first-order market-impact charge (gate B5).** `MARKET_IMPACT`
  (**default OFF**) adds a size-aware `impact% = 100·σ·√(Q/ADV)` term per leg on top of
  the half-spread (σ from the loaded closes, ADV = mean hourly $-vol × 24,
  Q = `usd_per_trade`). Every prior cost figure assumed $100/leg top-of-book and so
  **omitted impact entirely**. The key property: impact ∝ **Q^1.5** vs gross ∝ **Q**, so
  bigger manual size **erodes** the edge. Validated on the live cache — a thin alt
  (~$29k/hr, σ≈5%) costs ≈**0.19%/leg @ $1k**, ≈**0.42% @ $5k** (reproduces §4.3); BTC
  ≈0%. Backtest-only; honest cost at real size, **not** alpha. Combined with the
  strategy living in thin markets, this is why the +$187 (flat) / +$157 (per-market)
  taker figures are **optimistic** — the honest net at real size is lower still.
  `backend/simulation/market_impact.py`; see `docs/TRADING_CONCEPTS.md` (Part 5 "Market
  impact"), `docs/BACKTEST_PARAMETER_GUIDE.md` §C4, the 2026-07-25 `docs/QA.md` entry.

  **Gate-B5 size-aware re-run (2026-07-26, prod, `PER_MARKET_SLIPPAGE=on MARKET_IMPACT=on`).**
  entry-3.5 OOS at **$1,000/leg** (capital scaled to $100k → same 100 slots as the
  $100 baseline). Rows `b5-3.5-s2/s3/s4`
  (`cmrzgw10t0001zxtj6wb15k1f` / `cmrzgw12i0002zxtjorbgupf0` / `cmrzgw1510003zxtj8peufw3u`):

  | Span | Trades | Win% | Net @ $1k/leg (spread + impact) |
  |---|---|---|---|
  | s2 (2025-11-07→2026-03-01) | 3,565 | 57.9% | **−$22,012.71** |
  | s3 (2025-07-16→2025-11-07) | 2,611 | 55.0% | **−$28,726.33** |
  | s4 (2025-03-24→2025-07-16) | 1,495 | 55.8% | **+$69.14** |
  | **OOS total** | **7,671** | **~56%** | **−$50,669.90** |

  **The size ladder (gate B5 — decisive).** Per-market spread only: **+$157 @ $100/leg**
  → extrapolates to ≈ **+$1,570 @ $1k** (gross ∝ Q). Add market impact and the **$1k**
  net is **−$50,670** — a **−50% loss on $100k capital**. Impact alone costs **~$52k**
  (~$6–7/trade, ≈0.18%/leg avg — matching the §4.3 model), and the win rate collapses
  **~65% → ~56%** as impact flips thousands of small winners into losers. This is the
  plan's §4.3 warning — *"structurally unharvestable at real manual size"* — now
  measured. **Gate B5 fails hard.** ($5k/leg is worse still, but the √-law breaks down
  as many thin markets hit the 5%/leg impact cap, so no false-precision figure is given.)
  Combined with Slice 4 (nothing clears DSR > 0.95), the honest, size-aware, multiplicity-
  corrected verdict is an unambiguous **NO-GO** — exactly what the machinery was built to
  establish, cheaply and defensibly.

- **Slice 4 — multiple-testing correction (gate B3).** In-house **Deflated Sharpe
  Ratio** + **PBO/CSCV** (Bailey & López de Prado), stdlib only — no scipy/mlfinlab
  (`backend/stats/`). DSR = P(true Sharpe > the *expected max* of the search) after
  correcting for (a) the **number of configs tried** (69 — the "best" is plausibly the
  luckiest draw), (b) return non-normality, (c) sample length. **DSR > 0.95 clears gate
  B3.** Surfaced as a **"corrected significance" badge** on the strategy dashboard
  (`GET /api/backtest/significance` → `ui` `DsrBadge`), so no config is ever recommended
  on an uncorrected leaderboard. **PBO** is validated (≈1 on a synthetic overfit set,
  ≈0 on a dominant config) but *not* wired to the leaderboard — CSCV needs configs over
  identical windows, and the saved configs span different date ranges (s1–s4); it stays
  a tool for a controlled same-window overfitting study. This is the biggest
  *statistical* gap closed: the dashboard now answers "would this survive the search?",
  not just "what did this run produce?". `docs/QA.md` (2026-07-25 DSR entry); `statsmodels`
  is used only as a cointegration/half-life test oracle, never for DSR.

- **Slice 6 — phase tagging (non-destructive provenance).** Additive `phase Int
  @default(1)` on `Strategy` (`schema.prisma`, migration `0015_strategy_phase`): every
  existing row backfills to **phase 1** (the preserved baseline — **no row is ever
  deleted or hidden**), and the create path stamps new runs **phase 2**. The API returns
  `phase`; the dashboard shows a **"Phase 2" badge** beside the cost/span/DSR badges and
  a **Phase filter** (Phase 1 / Phase 2 / All, **default All**). An orthogonal provenance
  axis — a name-prefix convention was rejected (names are unreliable; 24 rows are
  "Untitled strategy"). Migration is additive + default-backfilled; on prod, `pg_dump`
  → `prisma migrate deploy`. Closes the operator requirement: tell phase-2 runs from
  phase-1 without ever losing the phase-1 evidence.

**Phase-2 verdict (final).** All six slices delivered the honest measurement + selection
machinery. Its verdict on today's signal is unambiguous: **NO-GO** — best honest OOS net
is a coin flip at $100/leg (+$157), collapses to **−$50,670 at $1k/leg** once market
impact is charged (gate B5 fails), and **nothing clears DSR > 0.95** (gate B3 fails). The
machinery now makes any *future* candidate provable or refutable cheaply.

---

## Phase-4 campaign — the entry × size interaction (2026-07-29 → 07-30)

**Verdict up front: NO-GO, unchanged.** This campaign found a real, reproducible
*mechanism* — raising entry selectivity inverts the size economics — but not a
defensible edge. The result fails gate B3's Deflated-Sharpe arm and is concentrated
in a handful of windows. Plan: `docs/PHASE4_TASKC_PLAN.md`.

**What was untested before this.** Every lever had been swept, but only ever at
**one size** ($100/leg), and the size ladder had only ever been measured at **one
entry** (3.5). Phase-1 could not explore that surface at all — it never charged
market impact. Two campaigns, 3 entry values × 3 OOS spans, honest cost flags on
(`PER_MARKET_SLIPPAGE` + `MARKET_IMPACT`), `scan 21 / trade 7`, 13 windows per span,
`stop 5.0` throughout to avoid the degenerate `entry == stop` at 4.0.

### Results

| Entry | s2 | s3 | s4 | **OOS total @ $100/leg** | Trades |
|---|---|---|---|---|---|
| 3.5 | +$115 | −$1,667 | +$306 | **−$1,246** | 7,699 |
| 3.75 | +$564 | +$297 | +$50 | **+$911** | 3,711 |
| 4.0 | +$1,385 | +$807 | +$154 | **+$2,346** | 1,513 |

| Entry | s2 | s3 | s4 | **OOS total @ $1,000/leg** | Trades |
|---|---|---|---|---|---|
| 3.5 | −$14,436 | −$29,899 | −$4,537 | **−$48,872** | 7,638 |
| 3.75 | −$2,178 | −$3,541 | −$2,655 | **−$8,374** | 3,706 |
| 4.0 | +$10,706 | +$4,796 | +$284 | **+$15,787** | 1,511 |

**Control validated.** The entry-3.5 arm at $1,000/leg reproduces the documented
gate-B5 figure: **−$48,872 vs the published −$50,670**, within 3.5% (the residual is
`stop 5.0` vs the reference's 4.0). The machinery is measuring what it did before.

### The mechanism, quantified

Impact cost per trade is **essentially constant across entry thresholds** — what
changes is how many trades pay it:

| Entry | Gross/trade @ $100 | 10× gross would be | Actual gross @ $1k | Impact absorbed | Impact/trade |
|---|---|---|---|---|---|
| 3.5 | $0.56 | $19,990 | $4,315 | $15,675 | **$4.41** |
| 3.75 | $1.06 | $18,620 | $10,779 | $7,841 | **$4.47** |
| 4.0 | $3.08 | $22,480 | $19,309 | $3,171 | **$4.35** |

Entry 4.0 wins at size for one reason: its **gross per trade is 5.5× higher** while
its **friction per trade is the same**, so it clears a per-trade tax that buries
entry 3.5. Gross scales as Q; impact as Q^1.5 — so the *number* of trades, not the
size, is the lever that decides whether the edge survives.

### Funding is the dominant explicit cost (Phase-4 Task A)

The per-trade cost columns shipped in Task A make this visible for the first time:

| Config (s2, $100/leg) | Gross | Fees | Funding | Net | Avg hold |
|---|---|---|---|---|---|
| e3.5 | +$1,999 | −$675 | **−$1,210** | +$115 | 10.9h |
| e4.0 | +$2,248 | −$133 | **−$730** | +$1,385 | 11.1h |

**Funding costs 1.8–5.5× more than fees** and eats 32–61% of gross. It scales
near-linearly with notional (e3.5/s2: −$1,210 → −$12,041 at 10× size, a
9.95× ratio), confirming it is a pure carry cost, not a microstructure one. The operator's
instinct to demand funding visibility was correct — it is the largest single
deduction, and it was previously buried inside net.

### Why this is still NO-GO

| Gate | entry 4.0 @ $1,000/leg | |
|---|---|---|
| B1 out-of-sample only | ✅ | s2/s3/s4, zero overlap with the tuned window |
| B2 real per-market taker cost | ✅ | per-market spread + size-aware impact |
| B3 net ≥ +$424 | ✅ | +$15,787 |
| B3 **DSR > 0.95** | ❌ | **0.0000** |
| B4 non-negative in ≥2 spans | ✅ | 3/3 |
| B5 executable at real size | ✅ | positive at $1,000/leg |

**The DSR failure is real arithmetic, not a defect.** With `n_trials = 72` and
trial-Sharpe dispersion 0.76, the multiplicity-corrected bar is
**`sr_star` = 1.839**; entry 4.0's window-return Sharpe is **0.26**. Nothing is close.

**And the reason is visible in the windows.** Of 13 windows per span, only 5–7 are
positive, and the best three carry the whole result:

| entry 4.0 @ $1k | Net | Best 3 windows | Other 10 windows |
|---|---|---|---|
| s2 | +$10,706 | +$17,998 | **−$7,292** |
| s3 | +$4,796 | +$7,403 | **−$2,607** |
| s4 | +$284 | +$6,556 | **−$6,271** |

Across all three spans: **9 of 39 windows produce +$31,957; the other 30 lose
−$16,170.** Strip the best three windows from any span and it goes negative. That is
not a broad edge — it is a small number of large wins, which is exactly the pattern
the Deflated Sharpe exists to catch.

**B3's two arms disagree, and the net arm is the weaker evidence here.** The +$424
threshold derives from a ±$212 noise floor estimated at *$100/leg on
entry-3.5-scale runs* (thousands of trades). It was never intended for 1,511 trades
whose P&L lives in 9 windows. DSR is the purpose-built correction for precisely this
situation, and it says no.

### Honest note on the prediction

`PHASE4_TASKC_PLAN.md` §3 pre-stated that entry 4.0 would land "near break-even and
still fail B3" at $1,000/leg. **The net figure was wrong** (+$15,787, not
break-even). The error is identifiable: the projection assumed the out-of-sample
haircut measured at entry 3.5 (27.8% of in-sample gross/trade) applied at every
threshold. It does not — more selective configs held up substantially better
out-of-sample. The *conclusion* (fails B3) survived, but for the DSR reason rather
than the net reason.

### What this changes

Nothing about deployment: `ENVIRONMENT` stays testnet, no strategy ships, no gate is
relaxed. What it does change is the **search direction**. "More selectivity at larger
size" is now measured, and the honest reading is that the surviving P&L is too
concentrated to trade. A genuine "yes" still needs what
`PHASE2_STRATEGY_PLAN.md` §7 says it needs — a **new signal**, most plausibly
funding-carry-aware pair selection, now that funding is measured as the single
largest cost line.
