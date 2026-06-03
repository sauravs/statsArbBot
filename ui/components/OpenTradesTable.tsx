"use client";

import { type LiveTrade } from "@/lib/api";

// Open live positions (PRD F5.5). Each row is a DB-backed two-leg trade opened by
// the entry scan; closed/aborted by the exit manager or the Abort-all control.
export default function OpenTradesTable({ trades }: { trades: LiveTrade[] }) {
  const open = trades.filter((t) => t.status === "OPEN");

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Open Trades
        <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
          {open.length}
        </span>
      </h2>

      {open.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted" data-testid="open-trades-empty">
          No open positions. Activate the bot and run an entry scan.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="open-trades-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">Sides (base / quote)</th>
                <th className="px-3 py-2 text-right">Size (base / quote)</th>
                <th className="px-3 py-2 text-right">Z @ entry</th>
                <th className="px-3 py-2 text-right">Entry (1 / 2)</th>
                <th className="px-3 py-2 text-right">Opened</th>
              </tr>
            </thead>
            <tbody>
              {open.map((t) => (
                <tr key={t.id} className="border-b border-border/50" data-testid="open-trade-row">
                  <td className="px-3 py-2 font-medium text-text">
                    {t.base_market}
                    <span className="text-muted"> / {t.quote_market}</span>
                  </td>
                  <td className="px-3 py-2">
                    <Side side={t.base_side} /> <span className="text-muted">/</span>{" "}
                    <Side side={t.quote_side} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.base_size.toFixed(4)} / {t.quote_size.toFixed(4)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {t.entry_z_score.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.entry_price_leg1.toFixed(2)} / {t.entry_price_leg2.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-muted">
                    {t.opened_at ? new Date(t.opened_at).toLocaleString() : "—"}
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

function Side({ side }: { side: string }) {
  const color = side === "BUY" ? "text-green" : "text-red";
  return <span className={`font-medium ${color}`}>{side}</span>;
}
