-- Persist each backtest trade's cointegration params (β/α/half-life) for its
-- formation window (issue #166), so a per-trade chart can reproduce the exact
-- spread (base − β·quote − α) and rolling z-score the backtest actually traded on.
-- Nullable & additive: trades recorded before this stay valid (they render the two
-- price panels; spread/z populate for trades run after this ships).
ALTER TABLE "backtest_trades" ADD COLUMN "hedge_ratio" DOUBLE PRECISION;
ALTER TABLE "backtest_trades" ADD COLUMN "intercept" DOUBLE PRECISION;
ALTER TABLE "backtest_trades" ADD COLUMN "half_life" DOUBLE PRECISION;
