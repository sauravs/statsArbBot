"use client";

import { useEffect, useState } from "react";
import { getDataInventory, type DataInventory } from "@/lib/api";
import InfoTip from "./InfoTip";

// Read-only inventory of the cached historical data (issue #80): a summary line
// plus a per-market coverage table (bars, date range, completeness). What the
// scan / sim / fast-forward / backtest engines actually run on. Fetching new data
// by date range is a separate feature (#81).
export default function DataInventoryPanel() {
  const [inv, setInv] = useState<DataInventory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDataInventory()
      .then(setInv)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load inventory"),
      );
  }, []);

  if (error) {
    return (
      <p className="text-sm text-red" data-testid="data-inventory-error">
        {error}
      </p>
    );
  }
  if (!inv) {
    return (
      <p className="text-sm text-muted" data-testid="data-inventory-loading">
        Loading inventory…
      </p>
    );
  }

  const s = inv.summary;
  return (
    <div className="space-y-6" data-testid="data-inventory">
      {/* Summary */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
          Cached History
          <InfoTip text="The OHLCV/funding candles stored locally that the scan, simulation, fast-forward, and backtest engines replay. Price data is always from the dYdX mainnet indexer." />
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Markets" value={String(s.market_count)} testid="di-markets" />
          <Stat
            label="Coverage"
            value={
              s.earliest && s.latest
                ? `${fmtDate(s.earliest)} → ${fmtDate(s.latest)}`
                : "—"
            }
            testid="di-coverage"
          />
          <Stat
            label="Bars"
            value={s.total_bars.toLocaleString()}
            testid="di-bars"
            tip={`Total cached ${inv.resolution} candles across all markets.`}
          />
          <Stat
            label="Funding"
            value={`${s.funding_markets} mkts · ${s.funding_rows.toLocaleString()} rows`}
            testid="di-funding"
            tip="Cached funding-rate history — the periodic carry cost the sim/backtest cost model applies."
          />
        </div>
      </div>

      {/* Per-market coverage */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
          Per-Market Coverage
          <InfoTip text="Each cached market: how many bars, the first→last date, and completeness — the fraction of a gapless series present (low values mean gaps that can quietly degrade a backtest)." />
        </h2>
        {inv.markets.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="di-empty">
            No cached data. Seed it with the ingest pipeline.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="di-table">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                  <th className="px-2 py-2 text-left">Market</th>
                  <th className="px-2 py-2 text-right">Bars</th>
                  <th className="px-2 py-2 text-left">First</th>
                  <th className="px-2 py-2 text-left">Last</th>
                  <th className="px-2 py-2 text-right">Completeness</th>
                </tr>
              </thead>
              <tbody>
                {inv.markets.map((m) => (
                  <tr
                    key={m.market}
                    className="border-b border-border/50"
                    data-testid="di-row"
                  >
                    <td className="px-2 py-2 font-medium text-text">{m.market}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">
                      {m.bars.toLocaleString()}
                    </td>
                    <td className="px-2 py-2 tabular-nums text-muted">{fmtDate(m.first)}</td>
                    <td className="px-2 py-2 tabular-nums text-muted">{fmtDate(m.last)}</td>
                    <td className="px-2 py-2">
                      <Completeness value={m.completeness} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Completeness({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.95 ? "#00d4a1" : value >= 0.8 ? "#ffd32a" : "#ff4757";
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-bg">
        <div className="h-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="w-9 text-right tabular-nums text-xs" style={{ color }}>
        {pct}%
      </span>
    </div>
  );
}

function Stat({
  label,
  value,
  testid,
  tip,
}: {
  label: string;
  value: string;
  testid: string;
  tip?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </p>
      <p className="mt-1 text-sm font-semibold text-text" data-testid={testid}>
        {value}
      </p>
    </div>
  );
}

/** ISO timestamp → YYYY-MM-DD. */
function fmtDate(iso: string): string {
  return iso.slice(0, 10);
}
