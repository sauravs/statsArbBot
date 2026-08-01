-- Real-time simulation: honest costs + per-session pair quality (Phase 5).
--
-- ADDITIVE and non-destructive: four NULLABLE columns default to NULL on every
-- existing sim_session, and NULL preserves today's behaviour exactly —
--   * pvalue_max / max_half_life_h  NULL = don't apply this bound (trade whatever
--     the latest scan produced, which is what every existing session did).
--   * per_market_slippage / market_impact  NULL = followed the process-global flag
--     at tick time; these are PROVENANCE, recorded so a paper run stays
--     reproducible after an env change (the same reason `strategies` carries its
--     own cost columns).
--
-- No row is rewritten and no default changes, so this is safe to apply to a live
-- database with running sessions.
ALTER TABLE "sim_sessions" ADD COLUMN "pvalue_max" DOUBLE PRECISION;
ALTER TABLE "sim_sessions" ADD COLUMN "max_half_life_h" DOUBLE PRECISION;
ALTER TABLE "sim_sessions" ADD COLUMN "per_market_slippage" BOOLEAN;
ALTER TABLE "sim_sessions" ADD COLUMN "market_impact" BOOLEAN;
