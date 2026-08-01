/**
 * Per-trade cost decomposition for the backtest blotter (Phase-4 Task A).
 *
 * The blotter used to show only Net P&L, which hides *why* a trade landed where
 * it did — in particular **funding**, which accrues with hold time and is the
 * cost the operator flagged as invisible. This module turns a persisted
 * `BacktestTrade` into the three components that sum to net:
 *
 *     gross + fees + funding = net
 *
 * where `fees` is returned **signed (≤ 0)** so all three read as the additive
 * contributions they are (the DB stores `fee_cost` as a positive magnitude and
 * the engine's identity is `net_pnl = gross_pnl − fee_cost + funding_pnl`; see
 * `backend/simulation/costs.py`).
 *
 * **Slippage and market impact are NOT a component here** — deliberately. The
 * engine charges them at the *fill price*
 * (`backend/simulation/costs.py::apply_slippage`, `simulation/market_impact.py`),
 * so they are already baked into `gross_pnl` and cannot be separated without an
 * engine change + migration. `SLIPPAGE_NOTE` is the tooltip that says so, so the
 * breakdown is never mistaken for a mid-price gross.
 */

/** The cost fields every persisted trade carries (a structural subset of
 *  `BacktestTrade`, so sim/FF trade shapes can reuse this too). */
export interface TradeCostFields {
  gross_pnl: number;
  fee_cost: number;
  funding_pnl: number;
  net_pnl: number;
  hold_hours: number;
}

export interface CostBreakdown {
  /** Realised P&L across both legs at their ACTUAL fill prices — already net of
   *  slippage and market impact (charged at the fill price, not as a line item). */
  gross: number;
  /** Taker fees, entry + exit, both legs. Signed ≤ 0. */
  fees: number;
  /** Funding, signed: a long leg pays, a short leg receives. Accrues with hold
   *  time, so it scales with `holdHours` — the pairing the operator asked for. */
  funding: number;
  net: number;
  holdHours: number;
  /** Did `gross + fees + funding` reconcile to the stored `net_pnl`? False marks
   *  a row whose components disagree with its net — a data defect worth showing
   *  rather than silently rendering four numbers that do not add up. */
  reconciles: boolean;
}

/** Half a cent: the engine rounds its components to 6dp, so anything beyond
 *  float noise is a genuine disagreement, not a rounding artefact. */
export const RECONCILE_TOLERANCE = 0.005;

/** Tooltip for the Gross column — states where slippage/impact actually live. */
export const SLIPPAGE_NOTE =
  "Realised P&L on both legs at their actual fill prices. Slippage and market " +
  "impact are already inside this number — the engine charges them at the fill " +
  "price rather than as a separate line item, so Gross is NOT a mid-price figure.";

/** Tooltip for the Fees column. */
export const FEES_NOTE =
  "Taker fee on every fill — entry and exit, both legs (4 fills per round-trip). " +
  "Always a deduction, so it is shown negative.";

/** Tooltip for the Funding column. */
export const FUNDING_NOTE =
  "Perp funding accrued over the hold, netted across the two legs: the long leg " +
  "pays and the short leg receives, so this can be + or −. It scales with how " +
  "long the position was held — compare it against the Hold column.";

/** Decompose one trade into the components that sum to its net P&L. */
export function costBreakdown(t: TradeCostFields): CostBreakdown {
  const gross = t.gross_pnl;
  const fees = -Math.abs(t.fee_cost);
  const funding = t.funding_pnl;
  const net = t.net_pnl;
  return {
    gross,
    fees,
    funding,
    net,
    holdHours: t.hold_hours,
    reconciles: Math.abs(gross + fees + funding - net) <= RECONCILE_TOLERANCE,
  };
}
