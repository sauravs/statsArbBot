import { describe, expect, it } from "vitest";
import {
  RECONCILE_TOLERANCE,
  costBreakdown,
  type TradeCostFields,
} from "@/lib/tradeCosts";

// Fixtures mirror the engine's own identity (backend/simulation/costs.py):
//   net_pnl = gross_pnl − fee_cost + funding_pnl
// with fee_cost stored as a POSITIVE magnitude and funding_pnl signed.

function trade(over: Partial<TradeCostFields> = {}): TradeCostFields {
  const gross_pnl = over.gross_pnl ?? 4.12;
  const fee_cost = over.fee_cost ?? 0.94;
  const funding_pnl = over.funding_pnl ?? -0.63;
  return {
    gross_pnl,
    fee_cost,
    funding_pnl,
    net_pnl: over.net_pnl ?? gross_pnl - fee_cost + funding_pnl,
    hold_hours: over.hold_hours ?? 31,
  };
}

describe("costBreakdown", () => {
  it("decomposes a winning trade into components that sum to net", () => {
    const b = costBreakdown(trade());
    expect(b.gross).toBeCloseTo(4.12, 6);
    expect(b.fees).toBeCloseTo(-0.94, 6);
    expect(b.funding).toBeCloseTo(-0.63, 6);
    expect(b.net).toBeCloseTo(2.55, 6);
    expect(b.gross + b.fees + b.funding).toBeCloseTo(b.net, 6);
    expect(b.reconciles).toBe(true);
  });

  it("returns fees signed negative so the column reads as a deduction", () => {
    // The DB stores fee_cost positive; the breakdown must not render "+$0.94"
    // next to a number that is subtracted.
    expect(costBreakdown(trade({ fee_cost: 0.94 })).fees).toBe(-0.94);
  });

  it("normalises an already-negative fee_cost rather than double-negating it", () => {
    // Defensive: a legacy/sim row that stored the fee signed must still show as
    // a single deduction, not flip back to a credit.
    const b = costBreakdown({
      gross_pnl: 4.12,
      fee_cost: -0.94,
      funding_pnl: -0.63,
      net_pnl: 2.55,
      hold_hours: 31,
    });
    expect(b.fees).toBe(-0.94);
    expect(b.reconciles).toBe(true);
  });

  it("keeps funding signed — a short-heavy pair can EARN funding", () => {
    const b = costBreakdown(trade({ funding_pnl: 1.87 }));
    expect(b.funding).toBeCloseTo(1.87, 6);
    expect(b.net).toBeCloseTo(4.12 - 0.94 + 1.87, 6);
    expect(b.reconciles).toBe(true);
  });

  it("surfaces hold_hours alongside funding (funding accrues with hold time)", () => {
    expect(costBreakdown(trade({ hold_hours: 172.5 })).holdHours).toBe(172.5);
  });

  it("reconciles a losing take-profit — the cohort where costs ate the revert", () => {
    // Spread reverted (gross positive) but fees + funding turned it red: the
    // exact case the blotter's "Losing take-profits" filter isolates.
    const b = costBreakdown(trade({ gross_pnl: 0.61, fee_cost: 0.9, funding_pnl: -0.4 }));
    expect(b.net).toBeCloseTo(-0.69, 6);
    expect(b.reconciles).toBe(true);
  });

  it("tolerates float noise within RECONCILE_TOLERANCE", () => {
    const b = costBreakdown(trade({ net_pnl: 2.55 + RECONCILE_TOLERANCE / 2 }));
    expect(b.reconciles).toBe(true);
  });

  it("flags a row whose components genuinely disagree with its net", () => {
    const b = costBreakdown(trade({ net_pnl: 9.99 }));
    expect(b.reconciles).toBe(false);
  });

  it("handles a zero-cost counterfactual run (fees and funding both 0)", () => {
    // The phase-1 cost-000 rows: gross IS net. Must not report a mismatch.
    const b = costBreakdown(trade({ gross_pnl: 3.3, fee_cost: 0, funding_pnl: 0 }));
    expect(b.fees).toBe(-0);
    expect(b.net).toBeCloseTo(3.3, 6);
    expect(b.reconciles).toBe(true);
  });

  it("reconciles a size-scaled phase-2 trade ($1k/leg, impact inside gross)", () => {
    // Gate-B5 shape: impact is charged at the fill price, so it shows up as a
    // depressed GROSS, never as its own component.
    const b = costBreakdown(trade({ gross_pnl: -5.4, fee_cost: 1.8, funding_pnl: 0.22 }));
    expect(b.net).toBeCloseTo(-6.98, 6);
    expect(b.reconciles).toBe(true);
  });
});
