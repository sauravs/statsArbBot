"use client";

import { useCallback, useEffect, useState } from "react";
import { getManualTrades, type ManualTrade } from "@/lib/api";
import CloseManualTradeModal from "./CloseManualTradeModal";

// Separate "Manual Trades" section (PRD F4.6) — not mixed with bot trades.
// Lists recorded trades with their lifecycle: OPEN trades can be marked closed
// (P&L computed), CLOSED trades show realised P&L.
export default function ManualTradesPanel({
  refreshKey,
}: {
  refreshKey: number;
}) {
  const [trades, setTrades] = useState<ManualTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<ManualTrade | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getManualTrades();
      setTrades(res.trades);
      setError(res.error ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load manual trades");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  return (
    <div className="mt-6 rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted">
          Manual Trades
          <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
            {trades.length}
          </span>
        </h2>
      </div>

      {error && <p className="mb-3 text-sm text-red">{error}</p>}

      {trades.length === 0 ? (
        <p
          className="py-8 text-center text-sm text-muted"
          data-testid="manual-empty"
        >
          No manual trades recorded yet. Set the Z-threshold, then record a trade
          from an active-signal pair.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="manual-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-right">Z @ entry</th>
                <th className="px-3 py-2 text-right">Capital (1 / 2)</th>
                <th className="px-3 py-2 text-right">Entry (1 / 2)</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">Status</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-border/50"
                  data-testid="manual-row"
                >
                  <td className="px-3 py-2 font-medium text-text">
                    {t.base_market}
                    <span className="text-muted"> / {t.quote_market}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {t.z_score.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.capital_leg1_usd.toFixed(0)} / {t.capital_leg2_usd.toFixed(0)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.entry_price_leg1.toFixed(2)} / {t.entry_price_leg2.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      t.pnl == null
                        ? "text-muted"
                        : t.pnl >= 0
                          ? "text-green"
                          : "text-red"
                    }`}
                    data-testid="manual-pnl"
                  >
                    {t.pnl == null ? "—" : t.pnl.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        t.status === "OPEN"
                          ? "bg-blue/20 text-blue"
                          : "bg-muted/20 text-muted"
                      }`}
                      data-testid="manual-status"
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {t.status === "OPEN" ? (
                      <button
                        onClick={() => setClosing(t)}
                        data-testid="close-trade-btn"
                        className="rounded border border-yellow px-2 py-1 text-xs text-yellow hover:bg-yellow/10"
                      >
                        Mark closed
                      </button>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {closing && (
        <CloseManualTradeModal
          trade={closing}
          onClose={() => setClosing(null)}
          onClosed={refresh}
        />
      )}
    </div>
  );
}
