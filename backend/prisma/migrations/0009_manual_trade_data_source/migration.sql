-- Tag each manual trade with the market-data source it was recorded under
-- ("fake" demo vs "dydx" live), so the dashboard can separate demo trades from
-- live ones without deleting either (issue #43 follow-up). Existing rows default
-- to the live source.
ALTER TABLE "manual_trades" ADD COLUMN "data_source" TEXT NOT NULL DEFAULT 'dydx';
