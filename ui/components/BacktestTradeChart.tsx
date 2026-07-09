"use client";

import { useEffect, useState } from "react";
import {
  fetchBacktestTradeSeries,
  type BacktestTradeOverlay,
  type BacktestTradeSeries,
} from "@/lib/api";
import PairCharts, { type EntryOverlay } from "./PairCharts";

// Map the API overlay (nulls) to PairCharts' EntryOverlay (undefined = absent).
function toOverlay(o: BacktestTradeOverlay): EntryOverlay {
  return {
    z: o.z ?? undefined,
    priceBase: o.priceBase ?? undefined,
    priceQuote: o.priceQuote ?? undefined,
    spread: o.spread ?? undefined,
    time: o.time ?? undefined,
  };
}

const dirLabel = (d: string) =>
  d === "LONG_BASE" ? "Long base / short quote" : d === "SHORT_BASE" ? "Short base / long quote" : d;

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const fmtT = (unix: number) =>
  new Date(unix * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";

/**
 * The per-trade chart (issue #166): fetches the trade's series (four pair panels
 * over its test window) and renders them via the shared PairCharts with the
 * trade's own entry (yellow) + exit (orange) markers. Trades run before β/α were
 * persisted show only the two price panels + a note.
 */
export default function BacktestTradeChart({
  strategyId,
  tradeId,
}: {
  strategyId: string;
  tradeId: string;
}) {
  const [data, setData] = useState<BacktestTradeSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchBacktestTradeSeries(strategyId, tradeId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Failed to load trade chart");
      });
    return () => {
      cancelled = true;
    };
  }, [strategyId, tradeId]);

  if (error) {
    return (
      <p className="py-10 text-center text-sm text-red" data-testid="bt-trade-chart-error">
        {error}
      </p>
    );
  }
  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted" data-testid="bt-trade-chart-loading">
        Loading trade chart…
      </p>
    );
  }

  const pnlTone = data.net_pnl >= 0 ? "text-green" : "text-red";

  return (
    <div data-testid="bt-trade-chart" className="space-y-4">
      {/* Trade summary */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <span className="font-semibold">
          {data.base_market} <span className="text-muted">/</span> {data.quote_market}
        </span>
        <span className="text-muted">{dirLabel(data.direction)}</span>
        <span className="tabular-nums text-muted">
          {/* Colors mirror the chart's vertical entry/exit lines — C.entryLine / C.exitLine (#172). */}
          <span style={{ color: "#22d3ee" }}>entry</span> {fmtT(data.entry.time)}
          {" → "}
          <span style={{ color: "#c084fc" }}>exit</span> {fmtT(data.exit.time)}
        </span>
        <span className={`tabular-nums font-semibold ${pnlTone}`}>{fmtUsd(data.net_pnl)}</span>
        <span className="rounded bg-bg px-1.5 py-0.5 text-xs text-muted">{data.exit_reason}</span>
      </div>

      {/* Legacy trades (pre-β/α capture): only the two price panels are faithful. */}
      {!data.faithful && (
        <div
          data-testid="bt-trade-chart-note"
          className="rounded-lg border border-yellow/40 bg-yellow/10 px-3 py-2 text-xs text-yellow"
        >
          Spread &amp; z-score aren&apos;t available for this trade — it was recorded before
          per-trade cointegration params were captured. The two price panels are exact;
          re-run the strategy to get the full four-panel chart.
        </div>
      )}

      <PairCharts
        base={data.base_market}
        quote={data.quote_market}
        series={data.series}
        entry={toOverlay(data.entry)}
        exit={toOverlay(data.exit)}
      />
    </div>
  );
}
