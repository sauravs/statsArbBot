"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type FFSimulation } from "@/lib/api";
import { FFStatusBadge } from "./FFSimList";

// Detail view for one fast-forward run (PRD F7.3): progress + result metrics, the
// equity curve, per-pair P&L, and the exit-reason breakdown. A RUNNING run shows a
// live progress bar and a Stop control; a finished run renders its saved aggregates.
export default function FFSimDetail({
  run,
  busy,
  onStop,
}: {
  run: FFSimulation;
  busy: boolean;
  onStop: () => void;
}) {
  const running = run.status === "RUNNING";
  const curve = (run.equity_curve ?? []).map((p) => ({
    t: p.t,
    equity: p.equity,
  }));
  const perPair = Object.entries(run.per_pair_pnl ?? {}).sort(
    (a, b) => b[1].net_pnl - a[1].net_pnl,
  );
  const exitReasons = Object.entries(run.exit_reasons ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-6" data-testid="ff-detail">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">
            {run.label || `Run ${run.id.slice(0, 6)}`}
          </h2>
          <FFStatusBadge status={run.status} />
        </div>

        {running && (
          <div className="mb-4" data-testid="ff-progress">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>Replaying… {run.processed_ticks}/{run.total_ticks} bars</span>
              <span className="tabular-nums">{Math.round(run.progress * 100)}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
              <div
                className="h-full bg-blue transition-all"
                style={{ width: `${Math.round(run.progress * 100)}%` }}
              />
            </div>
          </div>
        )}

        {run.status === "FAILED" && run.error && (
          <p className="mb-4 text-sm text-red" data-testid="ff-failed-error">
            {run.error}
          </p>
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Starting" value={fmtUsd(run.starting_capital)} testid="ff-start-cap" />
          <Metric
            label="Final"
            value={run.final_capital != null ? fmtUsd(run.final_capital) : "—"}
            testid="ff-final-cap"
          />
          <Metric
            label="Realised P&L"
            value={run.realised_pnl != null ? fmtUsd(run.realised_pnl) : "—"}
            tone={run.realised_pnl != null ? (run.realised_pnl >= 0 ? "green" : "red") : undefined}
            testid="ff-realised-pnl"
          />
          <Metric label="Trades" value={String(run.total_trades)} testid="ff-total-trades" />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted">
          <span>Pairs: <span className="text-text" data-testid="ff-pairs-count">{run.pairs_count}</span></span>
          <span>Bars: {run.total_ticks}</span>
          <span>Entry |Z|≥{run.entry_threshold}</span>
          <span>Exit |Z|&lt;{run.exit_threshold}</span>
          <span>Stop |Z|≥{run.stop_threshold}</span>
          {run.start_time && (
            <span>
              {run.start_time.slice(0, 10)} → {run.end_time?.slice(0, 10)}
            </span>
          )}
        </div>

        {running && (
          <div className="mt-5">
            <button
              onClick={onStop}
              disabled={busy}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red/60 hover:text-red disabled:opacity-40"
              data-testid="ff-stop-btn"
            >
              Stop
            </button>
          </div>
        )}
      </div>

      {/* Equity curve */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Equity Curve</h2>
        {curve.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="ff-equity-empty">
            No equity data yet.
          </p>
        ) : (
          <div className="h-64" data-testid="ff-equity-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curve} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid stroke="#21262d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="t"
                  tickFormatter={(t) => new Date(t * 1000).toISOString().slice(5, 10)}
                  stroke="#8b949e"
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                />
                <YAxis
                  stroke="#8b949e"
                  tick={{ fontSize: 11 }}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => `$${Math.round(v).toLocaleString()}`}
                  width={70}
                />
                <Tooltip
                  contentStyle={{
                    background: "#12141a",
                    border: "1px solid #21262d",
                    borderRadius: "0.5rem",
                    color: "#e4e6ea",
                    fontSize: "0.8rem",
                  }}
                  labelFormatter={(t) => new Date(Number(t) * 1000).toISOString().slice(0, 16).replace("T", " ")}
                  formatter={(v: number) => [fmtUsd(v), "Equity"]}
                />
                <Line type="monotone" dataKey="equity" stroke="#00d4a1" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Per-pair P&L + exit reasons */}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Per-Pair P&amp;L</h2>
          {perPair.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted" data-testid="ff-perpair-empty">
              No closed trades.
            </p>
          ) : (
            <table className="w-full text-sm" data-testid="ff-perpair-table">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                  <th className="px-2 py-2 text-left">Pair</th>
                  <th className="px-2 py-2 text-right">Trades</th>
                  <th className="px-2 py-2 text-right">Wins</th>
                  <th className="px-2 py-2 text-right">Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {perPair.map(([pair, b]) => (
                  <tr key={pair} className="border-b border-border/50" data-testid="ff-perpair-row">
                    <td className="px-2 py-2 font-medium text-text">{pair}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{b.trades}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{b.wins}</td>
                    <td className={`px-2 py-2 text-right tabular-nums ${b.net_pnl >= 0 ? "text-green" : "text-red"}`}>
                      {fmtUsd(b.net_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Exit Reasons</h2>
          {exitReasons.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted" data-testid="ff-exits-empty">
              No exits yet.
            </p>
          ) : (
            <ul className="space-y-2" data-testid="ff-exits-list">
              {exitReasons.map(([reason, count]) => (
                <li key={reason} className="flex items-center justify-between text-sm">
                  <span className="text-muted">{reason}</span>
                  <span className="tabular-nums text-text">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
  testid,
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
  testid: string;
}) {
  const color = tone === "green" ? "text-green" : tone === "red" ? "text-red" : "text-text";
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${color}`} data-testid={testid}>
        {value}
      </p>
    </div>
  );
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
