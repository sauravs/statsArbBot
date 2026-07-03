-- Persist the FRESH Engle-Granger p-value that gates a manual entry (issue
-- #147). Manual trading now re-validates a pair's cointegration + half-life on
-- fresh candles at record time (a stale scan can admit a pair whose
-- cointegration has since decayed); the re-checked p-value is stored alongside
-- the already-persisted half-life. Nullable so existing rows (recorded before
-- the re-validation gate) remain valid.
ALTER TABLE "manual_trades" ADD COLUMN "p_value" DOUBLE PRECISION;
