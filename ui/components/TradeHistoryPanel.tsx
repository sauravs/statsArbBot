"use client";

import { type LiveTrade } from "@/lib/api";

// Closed/errored live trades (PRD F5.5) with realised P&L and exit reason.
export default function TradeHistoryPanel({ trades }: { trades: LiveTrade[] }) {
  const history = trades.filter((t) => t.status === "CLOSED" || t.status === "ERROR");

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Trade History
        <span className="ml-2 rounded-full bg-muted/20 px-1.5 py-0.5 text-xs text-muted">
          {history.length}
        </span>
      </h2>

      {history.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted" data-testid="history-empty">
          No closed trades yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="history-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">Exit reason</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">Closed</th>
                <th className="px-3 py-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map((t) => (
                <tr key={t.id} className="border-b border-border/50" data-testid="history-row">
                  <td className="px-3 py-2 font-medium text-text">
                    {t.base_market}
                    <span className="text-muted"> / {t.quote_market}</span>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {t.exit_reason ?? (t.status === "ERROR" ? (t.error ?? "error") : "—")}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      t.pnl == null ? "text-muted" : t.pnl >= 0 ? "text-green" : "text-red"
                    }`}
                    data-testid="history-pnl"
                  >
                    {t.pnl == null ? "—" : t.pnl.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-muted">
                    {t.closed_at ? new Date(t.closed_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        t.status === "CLOSED"
                          ? "bg-muted/20 text-muted"
                          : "bg-red/20 text-red"
                      }`}
                      data-testid="history-status"
                    >
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
