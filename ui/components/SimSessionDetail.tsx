"use client";

import { useState } from "react";
import { type SimOverview } from "@/lib/api";
import { StatusBadge } from "./SimSessionList";

// Detail view for one simulation session (PRD F6.5): equity/PnL metrics, the
// lifecycle controls (tick / pause / resume / stop / top-up), open positions
// marked to market, and the realised-trade history.
export default function SimSessionDetail({
  overview,
  busy,
  onTick,
  onPause,
  onResume,
  onStop,
  onTopUp,
}: {
  overview: SimOverview;
  busy: boolean;
  onTick: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onTopUp: (amount: number) => void;
}) {
  const { session, positions, trades, equity, unrealized_pnl } = overview;
  // Realised P&L is the sum of closed-trade net P&L — NOT current − starting
  // capital, which would also count top-ups (capital added, not profit earned).
  const realised = trades.reduce((sum, t) => sum + t.net_pnl, 0);
  const stopped = session.status === "STOPPED";
  const [topup, setTopup] = useState("1000");
  // Number(topup) <= 0 is NaN-leaky (NaN <= 0 is false), so guard on a finite > 0.
  const topupNum = Number(topup);
  const topupValid = Number.isFinite(topupNum) && topupNum > 0;

  return (
    <div className="space-y-6" data-testid="sim-detail">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">
            {session.label || `Sim ${session.id.slice(0, 6)}`}
          </h2>
          <StatusBadge status={session.status} />
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Capital" value={fmtUsd(session.current_capital)} testid="sim-capital-val" />
          <Metric label="Equity" value={fmtUsd(equity)} testid="sim-equity-val" />
          <Metric
            label="Realised P&L"
            value={fmtUsd(realised)}
            tone={realised >= 0 ? "green" : "red"}
            testid="sim-realised-pnl"
          />
          <Metric
            label="Unrealised"
            value={fmtUsd(unrealized_pnl)}
            tone={unrealized_pnl >= 0 ? "green" : "red"}
            testid="sim-unrealised-pnl"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted">
          <span>Ticks: <span className="tabular-nums text-text" data-testid="sim-tick-count">{session.tick_count}</span></span>
          <span>Interval: {session.interval_seconds}s</span>
          <span>Entry |Z|≥{session.entry_threshold}</span>
          <span>Exit |Z|&lt;{session.exit_threshold}</span>
          <span>Stop |Z|≥{session.stop_threshold}</span>
        </div>

        {/* Controls */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            onClick={onTick}
            disabled={busy || stopped || session.status === "PAUSED"}
            className="ctl ctl-blue"
            data-testid="sim-tick-btn"
          >
            Run tick now
          </button>
          {session.status === "RUNNING" ? (
            <button onClick={onPause} disabled={busy} className="ctl" data-testid="sim-pause-btn">
              Pause
            </button>
          ) : (
            <button
              onClick={onResume}
              disabled={busy || stopped}
              className="ctl"
              data-testid="sim-resume-btn"
            >
              Resume
            </button>
          )}
          <button
            onClick={onStop}
            disabled={busy || stopped}
            className="ctl ctl-red"
            data-testid="sim-stop-btn"
          >
            Stop
          </button>
          <div className="ml-auto flex items-center gap-2">
            <input
              type="number"
              min="1"
              value={topup}
              onChange={(e) => setTopup(e.target.value)}
              disabled={stopped}
              className="w-24 rounded-lg border border-border bg-bg px-2 py-1.5 text-sm text-text"
              data-testid="sim-topup-input"
            />
            <button
              onClick={() => onTopUp(topupNum)}
              disabled={busy || stopped || !topupValid}
              className="ctl"
              data-testid="sim-topup-btn"
            >
              Top up
            </button>
          </div>
        </div>
      </div>

      <PositionsTable positions={positions} />
      <TradesTable trades={trades} />

      <style jsx>{`
        :global(.ctl) {
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          padding: 0.4rem 0.85rem;
          font-size: 0.8rem;
          color: #8b949e;
          transition: all 0.15s;
        }
        :global(.ctl:hover:not(:disabled)) {
          color: #e4e6ea;
          border-color: rgba(74, 144, 226, 0.6);
        }
        :global(.ctl:disabled) {
          opacity: 0.4;
        }
        :global(.ctl-blue) {
          background: rgba(74, 144, 226, 0.2);
          color: #4a90e2;
          border-color: transparent;
        }
        :global(.ctl-red:hover:not(:disabled)) {
          color: #ff4757;
          border-color: rgba(255, 71, 87, 0.6);
        }
      `}</style>
    </div>
  );
}

function PositionsTable({ positions }: { positions: SimOverview["positions"] }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Open Positions
        <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
          {positions.length}
        </span>
      </h2>
      {positions.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted" data-testid="sim-positions-empty">
          No open positions. Run a tick on a live signal to open one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="sim-positions-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">Direction</th>
                <th className="px-3 py-2 text-right">Z @ entry</th>
                <th className="px-3 py-2 text-right">Z now</th>
                <th className="px-3 py-2 text-right">Unrealised</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id} className="border-b border-border/50" data-testid="sim-position-row">
                  <td className="px-3 py-2 font-medium text-text">
                    {p.base_market}
                    <span className="text-muted"> / {p.quote_market}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={p.direction === "LONG_BASE" ? "text-green" : "text-red"}>
                      {p.direction}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.entry_z.toFixed(3)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {p.current_z != null ? p.current_z.toFixed(3) : "—"}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${pnlColor(p.unrealized_pnl)}`}>
                    {p.unrealized_pnl != null ? fmtUsd(p.unrealized_pnl) : "—"}
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

function TradesTable({ trades }: { trades: SimOverview["trades"] }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Trade History
        <span className="ml-2 rounded-full bg-muted/20 px-1.5 py-0.5 text-xs text-muted">
          {trades.length}
        </span>
      </h2>
      {trades.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted" data-testid="sim-trades-empty">
          No closed trades yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="sim-trades-table">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">Reason</th>
                <th className="px-3 py-2 text-right">Hold (h)</th>
                <th className="px-3 py-2 text-right">Z in / out</th>
                <th className="px-3 py-2 text-right">Net P&L</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-border/50" data-testid="sim-trade-row">
                  <td className="px-3 py-2 font-medium text-text">
                    {t.base_market}
                    <span className="text-muted"> / {t.quote_market}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted" data-testid="sim-trade-reason">
                    {t.exit_reason}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.hold_hours.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.entry_z.toFixed(2)} / {t.exit_z != null ? t.exit_z.toFixed(2) : "—"}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${pnlColor(t.net_pnl)}`} data-testid="sim-trade-pnl">
                    {fmtUsd(t.net_pnl)}
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

function pnlColor(n: number | null): string {
  if (n == null) return "text-muted";
  return n >= 0 ? "text-green" : "text-red";
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
