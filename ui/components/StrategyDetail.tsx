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
import { type Strategy } from "@/lib/api";
import { BacktestStatusBadge } from "./StrategyList";

// Detail for one strategy's walk-forward backtest (PRD F8.4): run/pause/stop/delete
// controls, headline metrics, the equity curve, the per-window walk-forward table,
// per-pair P&L, exit reasons, and the generated markdown report (reports viewer).
export default function StrategyDetail({
  strategy,
  busy,
  onRun,
  onPause,
  onStop,
  onDelete,
}: {
  strategy: Strategy;
  busy: boolean;
  onRun: () => void;
  onPause: () => void;
  onStop: () => void;
  onDelete: () => void;
}) {
  const s = strategy;
  const running = s.status === "RUNNING";
  const curve = (s.equity_curve ?? []).map((p) => ({ t: p.t, equity: p.equity }));
  const perWindow = s.per_window ?? [];
  const perPair = Object.entries(s.per_pair_pnl ?? {}).sort((a, b) => b[1].net_pnl - a[1].net_pnl);
  const exitReasons = Object.entries(s.exit_reasons ?? {}).sort((a, b) => b[1] - a[1]);
  const canResume = s.status === "PAUSED";
  // Clamp to [0,100] and guard NaN so a transient bad progress value can't render
  // "NaN%" or an invalid CSS width.
  const pct = Math.max(0, Math.min(100, Math.round((s.progress || 0) * 100)));

  return (
    <div className="space-y-6" data-testid="strategy-detail">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">
            {s.name}
            {s.rank != null && (
              <span className="ml-2 text-xs text-muted" data-testid="bt-rank">
                rank #{s.rank}
              </span>
            )}
          </h2>
          <BacktestStatusBadge status={s.status} />
        </div>
        {s.description && <p className="mb-3 text-xs text-muted">{s.description}</p>}

        {(running || s.status === "PAUSED") && (
          <div className="mb-4" data-testid="bt-progress">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>
                {running ? "Sweeping…" : "Paused at"} {s.processed_windows}/{s.total_windows} windows
              </span>
              <span className="tabular-nums">{pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
              <div
                className="h-full bg-blue transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {s.status === "FAILED" && s.error && (
          <p className="mb-4 text-sm text-red" data-testid="bt-failed-error">
            {s.error}
          </p>
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Net P&L" value={s.net_pnl != null ? fmtUsd(s.net_pnl) : "—"}
            tone={s.net_pnl != null ? (s.net_pnl >= 0 ? "green" : "red") : undefined}
            testid="bt-net-pnl" />
          <Metric label="Final" value={s.final_capital != null ? fmtUsd(s.final_capital) : "—"} testid="bt-final-cap" />
          <Metric label="Trades" value={String(s.total_trades)} testid="bt-total-trades" />
          <Metric label="Win rate" value={s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : "—"} testid="bt-win-rate" />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted">
          <span>Scan {s.scan_window_days}d / Trade {s.trade_window_days}d</span>
          <span>Z-window {s.zscore_window}</span>
          <span>Entry |Z|≥{s.entry_threshold}</span>
          <span>Exit |Z|&lt;{s.exit_threshold}</span>
          <span>Stop |Z|≥{s.stop_threshold}</span>
          <span>Windows {s.processed_windows}/{s.total_windows}</span>
        </div>

        {/* Controls */}
        <div className="mt-5 flex flex-wrap gap-2">
          {!running && (
            <button
              onClick={onRun}
              disabled={busy}
              className="rounded-lg bg-green/20 px-3 py-1.5 text-xs font-medium text-green transition-colors hover:bg-green/30 disabled:opacity-40"
              data-testid="bt-run-btn"
            >
              {canResume ? "Resume" : s.status === "PENDING" ? "Run backtest" : "Re-run"}
            </button>
          )}
          {running && (
            <>
              <button
                onClick={onPause}
                disabled={busy}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-yellow/60 hover:text-yellow disabled:opacity-40"
                data-testid="bt-pause-btn"
              >
                Pause
              </button>
              <button
                onClick={onStop}
                disabled={busy}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red/60 hover:text-red disabled:opacity-40"
                data-testid="bt-stop-btn"
              >
                Stop
              </button>
            </>
          )}
          {!running && (
            <button
              onClick={onDelete}
              disabled={busy}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red/60 hover:text-red disabled:opacity-40"
              data-testid="bt-delete-btn"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {/* Equity curve */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Equity Curve</h2>
        {curve.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="bt-equity-empty">
            No equity data yet.
          </p>
        ) : (
          <div className="h-64" data-testid="bt-equity-chart">
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

      {/* Walk-forward windows */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Walk-Forward Windows</h2>
        {perWindow.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="bt-perwindow-empty">
            No windows processed yet.
          </p>
        ) : (
          <table className="w-full text-sm" data-testid="bt-perwindow-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-2 py-2 text-left">#</th>
                <th className="px-2 py-2 text-left">Scan → Trade</th>
                <th className="px-2 py-2 text-right">Pairs</th>
                <th className="px-2 py-2 text-right">Trades</th>
                <th className="px-2 py-2 text-right">Net P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {perWindow.map((w) => (
                <tr key={w.index} className="border-b border-border/50" data-testid="bt-perwindow-row">
                  <td className="px-2 py-2 tabular-nums text-muted">{w.index}</td>
                  <td className="px-2 py-2 text-xs text-muted">
                    {w.scan_start.slice(0, 10)} → {w.trade_end.slice(0, 10)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted">{w.pairs}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted">{w.trades}</td>
                  <td className={`px-2 py-2 text-right tabular-nums ${w.net_pnl >= 0 ? "text-green" : "text-red"}`}>
                    {fmtUsd(w.net_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Per-pair P&L + exit reasons */}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Per-Pair P&amp;L</h2>
          {perPair.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted" data-testid="bt-perpair-empty">
              No closed trades.
            </p>
          ) : (
            <table className="w-full text-sm" data-testid="bt-perpair-table">
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
                  <tr key={pair} className="border-b border-border/50">
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
            <p className="py-6 text-center text-sm text-muted" data-testid="bt-exits-empty">
              No exits yet.
            </p>
          ) : (
            <ul className="space-y-2" data-testid="bt-exits-list">
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

      {/* Report viewer (F8.3) */}
      {s.report_md && (
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Report</h2>
          <pre
            className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-bg p-4 text-xs leading-relaxed text-muted"
            data-testid="bt-report"
          >
            {s.report_md}
          </pre>
        </div>
      )}
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
