-- Tag each backtest strategy with the market-data source it was created/run under
-- ("fake" demo vs "dydx" live), so the Backtest list shows demo strategies only in
-- demo and live only in live (issue #98) — same pattern as manual_trades.data_source.
-- Existing rows default to the live source.
ALTER TABLE "strategies" ADD COLUMN "data_source" TEXT NOT NULL DEFAULT 'dydx';

-- Widen the lookup index to include the new scope column.
DROP INDEX IF EXISTS "strategies_exchange_status_idx";
CREATE INDEX "strategies_exchange_data_source_status_idx" ON "strategies"("exchange", "data_source", "status");
