---
# Statistical Arbitrage & Pairs Trading — Research Report
*Research compiled for statsArbBot rewrite. Date: 2026-05-31*

---

## Why This Research Exists (Option B Evidence)

The original reference bot (`oldCodeRef_Main_Source`) and initial prototype (`oldCodeRef_Prototype`) were built with a simplified algorithm. This research documents the empirical and academic evidence for four specific improvements included in the rewrite ("Option B"):

| Improvement | Reference |
|---|---|
| Include intercept in spread formula: `spread = S1 - β*S2 - α` | Kostadinov (2015); QuantStart CADF article |
| Hard stop-loss at \|Z\| >= 3.5–4.0 | arXiv:1706.07021; QuantInsti (Jana) |
| Exit at \|Z\| < 0.4–0.5 instead of zero-crossing | arXiv:2412.12555; arXiv:2407.16103 |
| Half-life cap tightened from 200h to 48–72h | arXiv:2109.10662; QuantConnect OU pairs study |

**These are the only four changes from the reference algorithm.** All other improvements (Johansen test, regime filter, Kalman hedge ratio, dynamic sizing) are deferred to a later phase.

---

## Section 0A: Theoretical Abstract — Why These Changes Were Needed

### The Core Theoretical Claim of Pairs Trading

Pairs trading rests on one mathematical claim: if two price series are cointegrated, their spread is stationary — it has a finite, stable mean and variance, and will always revert to that mean. The entire strategy is a bet on that reversion happening before costs consume the profit.

This claim is either true or it is not. If it is true, the spread will revert and the trade is profitable. If it breaks down — cointegration fails — the spread trends indefinitely and the position bleeds out.

Everything in the algorithm is a consequence of taking that claim seriously:

- The spread formula must correctly isolate the stationary component
- Entry and exit thresholds must be calibrated to the actual reversion dynamics
- The half-life filter must ensure reversion is fast enough to be profitable after costs
- A stop-loss must exist for the case where the claim turns out to be false

### Why the Original Algorithm Falls Short on Each Dimension

**Dimension 1 — Spread Formula (intercept missing)**

The OLS regression `S1 = α + β * S2 + ε` produces two outputs: α (intercept) and β (hedge ratio). The stationary residual is ε = S1 - α - β*S2. The original code computes `spread = S1 - β*S2`, discarding α entirely.

When α is nonzero (which it nearly always is in crypto, where assets have different long-run growth rates), the "spread" is no longer the stationary residual — it is the stationary residual plus a constant drift. The z-score computed over a rolling window then centers around that drift rather than zero. The result: biased entry signals, asymmetric entry rates between long and short sides, and false exits. The fix is trivially a one-line change: subtract α from the spread formula.

**Dimension 2 — Half-Life Cap (200h is economically wrong for hourly trading)**

Half-life is not a statistical curiosity — it is a direct measure of trade profitability under costs. dYdX charges funding rates every hour. A position held for 8 days (200h half-life spread) accumulates 8 days × 24 hours of funding on both legs. The expected P&L from mean reversion must exceed those costs for the trade to be net positive.

The 200h cap in the prototype was set arbitrarily and is not calibrated to the cost structure of the exchange. The reference source's 24h cap is much closer to correct. The rewrite sets 72h — a conservative middle ground supported by the QuantConnect OU study on hourly data.

**Dimension 3 — Exit at |Z| < 0.5 (zero-crossing exit is theoretically suboptimal with transaction costs)**

In a frictionless world, waiting for full reversion (zero-crossing) maximizes expected P&L per trade. In the real world — with funding rates accruing hourly — the last portion of reversion (from |Z| = 0.5 back to zero) often takes as long as the first portion (from |Z| = 1.5 to |Z| = 0.5), but earns less. Optimal stopping theory (Leung & Li 2015) proves the optimal exit threshold is strictly inside zero when carry costs are nonzero. The empirical optimum from grid search across both equity (arXiv:2412.12555) and crypto (arXiv:2407.16103) data converges around 0.37–0.4 standard deviations. Using |Z| < 0.5 is the practical implementation of this finding.

**Dimension 4 — Hard Stop-Loss (the original has none)**

The `STOP_LOSS_ZSCORE` constant exists in the prototype's constants file but is never wired into the exit logic. This means a trade that opens at |Z| = 1.5 and diverges to |Z| = 10 will be held indefinitely. This is not a theoretical concern — in crypto, cointegration breaks down frequently and suddenly (delistings, protocol forks, BTC correlation regime shifts). Without a stop-loss, a single cointegration breakdown event can wipe out months of profitable trades. The stop-loss at |Z| >= 4.0 is the minimum viable risk control, supported by the first-exit-time analysis in arXiv:1706.07021.

### The Unified Picture

All four changes address the same root problem: the original algorithm was built with theoretically correct cointegration machinery but economically incorrect signal parameters. It would work in backtests on clean data but fail in live trading on dYdX because:

1. The spread formula introduces systematic bias (intercept issue)
2. The pair filter admits pairs that are too slow to be profitable after funding costs (half-life issue)
3. Positions are held longer than optimal (exit threshold issue)
4. There is no protection against cointegration regime changes (stop-loss issue)

The rewrite fixes all four without touching the core cointegration engine, keeping the changeset minimal and verifiable.

---

## Section 0: Theoretical Foundation

### What Is Statistical Arbitrage / Pairs Trading?

Statistical arbitrage exploits temporary mispricings between financially related assets. In pairs trading, two assets whose prices have historically moved together (are "cointegrated") diverge temporarily. The strategy bets on reversion to their historical equilibrium.

### Core Mathematical Concepts

**Cointegration:** Two non-stationary price series S1 and S2 are cointegrated if there exists a linear combination `S1 - β*S2` that IS stationary (mean-reverting). This is stronger than correlation — it implies a long-run equilibrium relationship.

**Hedge Ratio (β):** The OLS regression coefficient from `S1 = α + β*S2 + ε`. Tells you how many units of S2 to short/long for each unit of S1.

**Spread:** `spread_t = S1_t - β*S2_t - α`. The residual from the cointegrating regression. Should be stationary (mean-reverting to zero) if the pair is truly cointegrated.

**Ornstein-Uhlenbeck (OU) Process:** A continuous-time stochastic process that mean-reverts. The spread of a cointegrated pair follows an OU process: `dX = θ(μ - X)dt + σdW`. The speed of reversion θ determines how quickly the spread returns to equilibrium.

**Half-Life:** Derived from OU calibration: `half_life = ln(2) / θ`. Tells you the average time for the spread to revert halfway to its mean. Shorter half-life = faster mean reversion = better trading pair.

**Z-Score:** `z = (spread - rolling_mean) / rolling_std`. Measures how many standard deviations the current spread is from its recent mean. Used as the trading signal: large |Z| = significant mispricing.

### The Trading Signal Logic

```
Entry: |Z| >= 1.5
  Z < 0 → spread below mean → BUY base, SELL quote (bet spread will rise)
  Z > 0 → spread above mean → SELL base, BUY quote (bet spread will fall)

Exit: |Z| < 0.5 (or zero-crossing in simpler implementations)
  Spread has reverted toward mean → close both legs → take profit

Stop-Loss: |Z| >= 4.0
  Spread is diverging further → cointegration may be breaking down → cut losses
```

---

## Section 1: Engle-Granger Cointegration — Known Weaknesses

The Engle-Granger (EG) two-step method is the original cointegration test (1987). It runs OLS regression to estimate the hedge ratio, then applies an ADF unit-root test to the residuals.

### Key Weaknesses for Crypto

1. **Variable-order sensitivity (asymmetry):** Results depend on which asset is chosen as the dependent variable. Run both directions; take the more negative ADF t-statistic. `statsmodels.coint()` handles this effectively.

2. **Single cointegrating relationship:** Cannot detect multiple cointegrating vectors across 3+ assets (Johansen handles this — deferred to Phase 2).

3. **OLS endogeneity bias:** Crypto price series often have feedback loops. While EG is super-consistent asymptotically, finite-sample bias is meaningful on hourly/daily crypto data.

4. **Cointegration instability:** Crypto is prone to structural breaks (exchange collapses, BTC halvings, protocol events). EG with a fixed window cannot detect breakdown in real-time.

5. **Nonlinear dynamics:** Standard EG cannot capture threshold cointegration or asymmetric adjustment. The KSS test handles this but is deferred to Phase 2.

**Sources:**
- [Limitations of the Engle-Granger Test — Economics.Town](https://economics.town/advanced-econometric-methods/limitations-engle-granger-cointegration-test/)
- [Evaluation of Dynamic Cointegration-Based Pairs Trading in Crypto — arXiv:2109.10662](https://arxiv.org/abs/2109.10662)
- [Cointegration-based pairs trading — Springer 2025](https://link.springer.com/article/10.1057/s41260-025-00416-0)

### Alternatives (Deferred to Phase 2)
- **Johansen test:** Symmetric, identifies multiple cointegrating vectors. Preferred by ArbitrageLab and QuantConnect for production systems.
- **KSS test:** Nonlinear unit-root test, captures asymmetric mean reversion.

---

## Section 2: Spread Formula — Why the Intercept Matters (Option B)

### The Two Formulations

- **Without intercept (original reference code):** `spread_t = S1_t - β * S2_t`
- **With intercept (rewrite):** `spread_t = S1_t - β * S2_t - α`

### Evidence for Including the Intercept

When one asset consistently outperforms the other over the formation window (very common in crypto), forcing α = 0 creates systematically biased residuals — the spread drifts rather than mean-reverts.

The OLS regression `S1 = α + β * S2 + ε` produces both α and β. The residuals ε are what get tested for stationarity in Engle-Granger. Using `spread = S1 - (α + β * S2)` ensures the spread is centered at zero around its true equilibrium.

Without the intercept: the z-score window will center around a nonzero drift mean, reducing signal quality and increasing false positives.

**Sources:**
- [Cointegration and the Role of the Intercept — Fabian Kostadinov](https://fabian-kostadinov.github.io/2015/01/04/cointegration-and-the-role-of-the-intercept/)
- [CADF Test for Pairs Trading — QuantStart](https://www.quantstart.com/articles/Cointegrated-Augmented-Dickey-Fuller-Test-for-Pairs-Trading-Evaluation-in-R/)
- [Constructing Strategy with Logs, Hedge Ratios, Z-Scores — Amberdata](https://blog.amberdata.io/constructing-your-strategy-with-logs-hedge-ratios-and-z-scores)

---

## Section 3: Z-Score Window — Relationship to Half-Life

A fixed 21-period window is theoretically unmotivated. The correct approach:

**Rule of thumb:** Set the lookback window to 2–3× the OU half-life of the spread. If a pair has a half-life of 20 hours, use a 40–60 bar window.

### Empirical Evidence
- RL paper (arXiv:2407.16103): Optimal window = 900 intervals on 1-minute BTC data (~15 hours lookback)
- QuantConnect OU pairs: uses 43-day lookback for pairs with half-life up to 42 days on daily data

**For rewrite:** Keep configurable `WINDOW` constant; document it should equal 2–3× the median half-life of active pairs. Default remains 21 as a conservative starting point.

---

## Section 4: Half-Life Filter — Evidence for Tighter Cap (Option B)

### Current State
- Reference source: `MAX_HALF_LIFE = 24` hours
- Prototype: `MAX_HALF_LIFE = 200` hours

### Evidence the 200h Cap Is Too Loose

At 200h half-life, the spread reverts halfway within ~8.3 days. On hourly-bar trading:
- Positions held for potentially weeks, accumulating dYdX hourly funding rates
- Very few trading opportunities per week
- Funding drag makes slow-reverting pairs unprofitable

**QuantConnect optimal OU pairs study:** Max half-life = 42 days for **daily** data. For **hourly** data, the equivalent practical upper bound is 48–72 hours for active trading.

**arXiv:2109.10662:** Calibrates OU half-life to determine lookback window, confirming fast-reverting pairs (hours, not days) are preferred for hourly-bar crypto trading.

**Recommended cap for rewrite:** 72 hours (aligns closer to the reference source's 24h intent than the prototype's 200h).

**Sources:**
- [arXiv:2109.10662](https://arxiv.org/abs/2109.10662)
- [QuantConnect OU Pairs](https://www.quantconnect.com/forum/discussion/9265/strategy-library-addition-optimal-pairs-trading-through-ornstein-uhlenbeck-modeling/)
- [Mean Reversion — Letian Zhang](https://letianzj.github.io/mean-reversion.html)

---

## Section 5: Exit Threshold — Evidence for |Z| < 0.5 Over Zero-Crossing (Option B)

### Zero-Crossing Exit (Original Approach)
Close position when z-score changes sign. Simple and theoretically sound.

### Evidence for Tighter Exit

**arXiv:2412.12555 (Parameters Optimization of Pair Trading):**
Grid-searched exit thresholds on S&P 500 pairs. Found optimal exit at **θ_out = 0.37 standard deviations**.

**arXiv:2407.16103 (RL Pairs Trading, crypto data):**
Found optimal close threshold of **0.4 z-scores** through grid search on BTC-GBP/EUR.

**Academic optimal control (Kim & Viens 2012; Leung & Li 2015):**
The optimal exit threshold is strictly inside zero when transaction costs are included. Expected gain from holding to zero < cost of carrying the position (especially with dYdX's hourly funding rates).

**dYdX-specific factor:**
Funding rates accumulate hourly. On a zero-crossing exit, you hold through the full reversion, accumulating hours to days of funding cost. Exiting at |Z| < 0.5 reduces average holding time and funding drag without meaningfully reducing expected P&L.

**Sources:**
- [arXiv:2412.12555](https://arxiv.org/html/2412.12555v1)
- [arXiv:2407.16103](https://arxiv.org/html/2407.16103v2)
- [Optimal Stopping in Pairs Trading — Hudson & Thames](https://hudsonthames.org/optimal-stopping-in-pairs-trading-ornstein-uhlenbeck-model/)

---

## Section 6: Stop-Loss — Critical Risk Control (Option B)

### Evidence: Hard Stop-Loss Is Essential

The primary risk in pairs trading is cointegration breakdown — the spread trends indefinitely rather than reverts. On crypto: delistings, exchange hacks, protocol changes, BTC correlation spikes.

### Published Stop-Loss Thresholds

| Source | Entry Z | Stop-Loss Z | Ratio |
|---|---|---|---|
| QuantInsti / Sabir Jana | ±2.0 | ±4.0 | 2:1 |
| Standard practitioner range | ±2.0 | ±3.0 | 1.5:1 |
| QuantPedia Zero-Crossing | 2–4σ | ±8.0 | variable |

**arXiv:1706.07021 ("Stop-loss and Leverage in Optimal Statistical Arbitrage"):**
Derives optimal stop-loss using expected first-exit times under OU process. Z-score of 3–4 is the practical proxy.

**Recommendation for rewrite:** With entry at |Z| >= 1.5: stop-loss at |Z| >= 4.0. Also add a time-based stop: close any position held longer than 3× the OU half-life (signals cointegration breakdown).

**Sources:**
- [arXiv:1706.07021](https://arxiv.org/abs/1706.07021)
- [QuantPedia — Zero-Crossing Pairs Trading](https://quantpedia.com/zero-crossing-variant-of-pairs-trading-strategy/)
- [Analytics Vidhya — Statistical Arbitrage with Pairs Trading](https://medium.com/analytics-vidhya/statistical-arbitrage-with-pairs-trading-and-backtesting-ec657b25a368)

---

## Section 7: Zero-Crossings as Pair Quality Metric

**Empirically validated.** Do and Faff (2010) showed statistically significant coefficients for zero-crossings correlating with improved pair returns. Higher zero-crossing frequency = stronger evidence of reliable mean reversion.

### Complementary Metrics (Phase 2)

| Metric | What It Measures |
|---|---|
| ADF p-value on residuals | Spread stationarity significance |
| OU half-life | Mean-reversion speed |
| Hurst exponent (H < 0.5) | Confirms mean-reverting vs. trending |
| Rolling cointegration stability | Is cointegration persistent or episodic? |

**Source:** [Distance Approach in Pairs Trading — Hudson & Thames](https://hudsonthames.org/distance-approach-in-pairs-trading-part-i/)

---

## Section 8: Regime Detection (Deferred to Phase 2)

Pairs trading underperforms in trending/high-volatility markets. Regime detection can reduce max drawdown significantly.

### Approaches (Phase 2)

1. **HMM (2-state):** Open new positions only in low-volatility state. Reduced max drawdown from 56% to 24% in QuantStart study.
2. **BTC rolling volatility filter:** Suspend when BTC 30-day realized vol > 80th percentile.
3. **Rolling ADF p-value:** Suspend when p > 0.10 (spread no longer stationary).
4. **Hurst exponent filter:** Only trade when H < 0.45.
5. **dYdX funding rate signal:** Persistent one-sided funding indicates directional pressure.

---

## Section 9: Current Best Practices (2024–2026)

### Significant Recent Improvements

1. **Dynamic cointegration (rolling Johansen):** Re-run test every N bars, update hedge ratios dynamically. [Frontiers 2026](https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1749337/full)

2. **Copula-based signal generation:** Combines cointegration with copula families; captures nonlinear dependence. [Financial Innovation 2025](https://link.springer.com/article/10.1186/s40854-024-00702-7)

3. **ML clustering for pair selection:** K-means/DBSCAN on crypto feature spaces before cointegration tests. [ResearchGate 2025](https://www.researchgate.net/publication/389262577_Enhancing_Pairs_Trading_Strategies_in_the_Cryptocurrency_Industry_using_Machine_Learning_Clustering_Algorithms)

4. **RL with dynamic sizing:** Dynamic scaling achieved 31.53% cumulative return vs. 8.33% baseline. [arXiv:2407.16103](https://arxiv.org/html/2407.16103v2)

5. **Structural break detection:** Rolling ADF or CUSUM test to pause when cointegration breaks down. [Springer 2021](https://link.springer.com/article/10.1007/s11227-021-04013-x)

### Performance Benchmarks
- Genetic algorithm optimized: Sharpe 1.53, max drawdown 29%
- RL with dynamic sizing: 31.53% cumulative return (1-min BTC data)
- Cointegration-based (BTC/ETH/LTC/XRP, 2022–2024): Sharpe 1.58–2.45
- QuantInsti perpetual contract: Sharpe 1.11–1.14

---

## Section 10: Position Sizing

### Comparison

| Approach | Pros | Cons |
|---|---|---|
| Fixed notional ($100/leg) | Simple, capital-controlled | Doesn't scale with signal strength |
| Z-score proportional | Scales with confidence, 3× empirical outperformance | Requires cap to avoid over-sizing |
| Kelly Criterion | Theoretically optimal | Model-dependent, unstable on crypto |

**Phase 1 (this rewrite):** Fixed $100/leg — keep for stability.

**Phase 2 upgrade:** `position_size = $100 * min(|Z| / 1.5, 3.0)` — scales 1×–3× for Z = 1.5–4.5.

---

## Full Reference List

- [arXiv:2109.10662 — Dynamic Cointegration Pairs Trading in Crypto](https://arxiv.org/abs/2109.10662)
- [arXiv:2407.16103 — RL Pair Trading: Dynamic Scaling](https://arxiv.org/html/2407.16103v2)
- [arXiv:2412.12555 — Parameters Optimization of Pair Trading](https://arxiv.org/html/2412.12555v1)
- [arXiv:1706.07021 — Stop-loss and Leverage in Optimal StatArb](https://arxiv.org/abs/1706.07021)
- [Frontiers 2026 — Deep learning-based crypto pairs trading](https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1749337/full)
- [Financial Innovation 2025 — Copula-based cointegrated crypto pairs](https://link.springer.com/article/10.1186/s40854-024-00702-7)
- [Springer 2025 — Cointegration-based pairs trading](https://link.springer.com/article/10.1057/s41260-025-00416-0)
- [Springer 2021 — Structural break-aware pairs trading DRL](https://link.springer.com/article/10.1007/s11227-021-04013-x)
- [Krauss 2017 — Statistical Arbitrage Review](https://onlinelibrary.wiley.com/doi/10.1111/joes.12153)
- [CREM WP 2024-11 — Genetic algorithm pairs trading](https://ideas.repec.org/p/tut/cremwp/2024-11.html)
- [Hudson & Thames — Introduction to Cointegration](https://hudsonthames.org/an-introduction-to-cointegration/)
- [Hudson & Thames — Distance Approach in Pairs Trading](https://hudsonthames.org/distance-approach-in-pairs-trading-part-i/)
- [Hudson & Thames — Optimal Stopping in Pairs Trading (OU)](https://hudsonthames.org/optimal-stopping-in-pairs-trading-ornstein-uhlenbeck-model/)
- [Hudson & Thames — Pairs Trading with Markov Regime-Switching](https://hudsonthames.org/pairs-trading-with-markov-regime-switching-model/)
- [QuantStart — CADF Test for Pairs Trading](https://www.quantstart.com/articles/Cointegrated-Augmented-Dickey-Fuller-Test-for-Pairs-Trading-Evaluation-in-R/)
- [QuantStart — Kalman Filter Pairs Trading](https://www.quantstart.com/articles/kalman-filter-based-pairs-trading-strategy-in-qstrader/)
- [QuantStart — Market Regime Detection HMMs](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/)
- [QuantConnect — Optimal OU Pairs Trading](https://www.quantconnect.com/forum/discussion/9265/strategy-library-addition-optimal-pairs-trading-through-ornstein-uhlenbeck-modeling/)
- [Amberdata — Crypto Pairs Trading: Cointegration vs Correlation](https://blog.amberdata.io/crypto-pairs-trading-why-cointegration-beats-correlation)
- [Amberdata — Constructing Strategy with Logs, Hedge Ratios, Z-Scores](https://blog.amberdata.io/constructing-your-strategy-with-logs-hedge-ratios-and-z-scores)
- [Kostadinov — Cointegration and the Role of the Intercept](https://fabian-kostadinov.github.io/2015/01/04/cointegration-and-the-role-of-the-intercept/)
- [dYdX Documentation — Funding](https://docs.dydx.xyz/concepts/trading/funding)
- [QuantPedia — Zero-Crossing Variant of Pairs Trading](https://quantpedia.com/zero-crossing-variant-of-pairs-trading-strategy/)
- [ResearchGate 2025 — ML Clustering for Crypto Pairs](https://www.researchgate.net/publication/389262577_Enhancing_Pairs_Trading_Strategies_in_the_Cryptocurrency_Industry_using_Machine_Learning_Clustering_Algorithms)
- [Mean Reversion — Letian Zhang](https://letianzj.github.io/mean-reversion.html)

---
*End of research.md*
