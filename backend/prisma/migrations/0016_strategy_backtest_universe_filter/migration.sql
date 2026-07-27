-- Per-strategy backtest universe liquidity/spread filter (Phase-3 WS1, path b).
-- ADDITIVE and non-destructive: two NULLABLE columns default to NULL on every
-- existing row (NULL = OFF → fall back to the global env default, itself OFF), so
-- no saved strategy's behaviour or data changes. When set on a new run, the
-- walk-forward prunes its market universe before the scan. HONESTY/robustness
-- knob, NOT alpha (filtering up loses money — PHASE2_STRATEGY_PLAN §4).
ALTER TABLE "strategies" ADD COLUMN "backtest_min_dollar_volume" DOUBLE PRECISION;
ALTER TABLE "strategies" ADD COLUMN "backtest_max_half_spread_pct" DOUBLE PRECISION;
