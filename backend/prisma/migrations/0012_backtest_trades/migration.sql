-- Per-trade blotter for walk-forward backtests (issue #162). The engine replays
-- each test window through the shared tick core producing full trade records but
-- previously discarded them, keeping only aggregates. Persisting each trade —
-- stamped with the walk-forward window it belongs to — lets the UI drill into a
-- window and see where/when each trade entered & exited (Z + leg prices) and the
-- exit rationale. Purely additive: no existing rows are touched.

-- Record the per-leg entry/exit fill prices on sim trades too (the shared close
-- path now captures them). Nullable so rows written before this stay valid.
ALTER TABLE "sim_trades" ADD COLUMN "entry_base_px" DOUBLE PRECISION;
ALTER TABLE "sim_trades" ADD COLUMN "entry_quote_px" DOUBLE PRECISION;
ALTER TABLE "sim_trades" ADD COLUMN "exit_base_px" DOUBLE PRECISION;
ALTER TABLE "sim_trades" ADD COLUMN "exit_quote_px" DOUBLE PRECISION;

-- CreateTable
CREATE TABLE "backtest_trades" (
    "id" TEXT NOT NULL,
    "strategy_id" TEXT NOT NULL,
    "window_index" INTEGER NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "direction" TEXT NOT NULL,
    "entry_time" TIMESTAMPTZ NOT NULL,
    "exit_time" TIMESTAMPTZ NOT NULL,
    "hold_hours" DOUBLE PRECISION NOT NULL,
    "entry_z" DOUBLE PRECISION NOT NULL,
    "exit_z" DOUBLE PRECISION,
    "entry_base_px" DOUBLE PRECISION,
    "entry_quote_px" DOUBLE PRECISION,
    "exit_base_px" DOUBLE PRECISION,
    "exit_quote_px" DOUBLE PRECISION,
    "exit_reason" TEXT NOT NULL,
    "notional_usd" DOUBLE PRECISION NOT NULL,
    "gross_pnl" DOUBLE PRECISION NOT NULL,
    "fee_cost" DOUBLE PRECISION NOT NULL,
    "funding_pnl" DOUBLE PRECISION NOT NULL,
    "net_pnl" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "backtest_trades_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "backtest_trades_strategy_id_window_index_idx" ON "backtest_trades"("strategy_id", "window_index");

-- AddForeignKey
ALTER TABLE "backtest_trades" ADD CONSTRAINT "backtest_trades_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "strategies"("id") ON DELETE CASCADE ON UPDATE CASCADE;
