-- Capture REALISED execution on manual trades so slippage is measurable.
--
-- The backtest charges a modelled `slippage_pct` per fill, but the true cost of
-- a market order is only knowable from real fills. Until now a manual trade
-- stored the server-captured REFERENCE price at entry (`entry_price_leg*`) and
-- the operator's ACTUAL fill at exit (`exit_price_leg*`) — so neither leg of the
-- comparison was complete and realised slippage could not be computed.
--
-- These four columns close both gaps:
--   * `fill_price_leg*`     — the operator's ACTUAL entry fill, to pair with the
--                             existing `entry_price_leg*` reference.
--   * `exit_ref_price_leg*` — the REFERENCE captured server-side at close time,
--                             to pair with the existing `exit_price_leg*` fill.
--
-- Realised slippage per leg then falls out as
--   entry: (fill_price − entry_price) / entry_price
--   exit:  (exit_price − exit_ref_price) / exit_ref_price
-- signed by the leg's side (a BUY filling high and a SELL filling low are both
-- adverse), which is the same convention as `simulation/costs.apply_slippage`.
--
-- All nullable and additive: existing rows remain valid, and the entry-fill
-- inputs stay optional for operators who do not record them.
ALTER TABLE "manual_trades" ADD COLUMN "fill_price_leg1" DOUBLE PRECISION;
ALTER TABLE "manual_trades" ADD COLUMN "fill_price_leg2" DOUBLE PRECISION;
ALTER TABLE "manual_trades" ADD COLUMN "exit_ref_price_leg1" DOUBLE PRECISION;
ALTER TABLE "manual_trades" ADD COLUMN "exit_ref_price_leg2" DOUBLE PRECISION;
