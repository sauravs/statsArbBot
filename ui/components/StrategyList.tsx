"use client";

import { type BacktestStatus, type Strategy } from "@/lib/api";

// Ranked strategy comparison (PRD F8.4): every strategy with its rank, key params,
// status, and net P&L, best-first. Selecting a row drives the detail view. The seed
// button creates the S1–S4 baseline set.
export default function StrategyList({
  strategies,
  selectedId,
  onSelect,
  onSeed,
  seeding,
}: {
  strategies: Strategy[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onSeed: () => void;
  seeding: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-muted">
          Strategies
          <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
            {strategies.length}
          </span>
        </h2>
        <button
          onClick={onSeed}
          disabled={seeding}
          className="rounded-lg border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-blue/60 hover:text-text disabled:opacity-40"
          data-testid="seed-defaults-btn"
        >
          {seeding ? "Seeding…" : "Seed S1–S4"}
        </button>
      </div>

      {strategies.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted" data-testid="strategy-list-empty">
          No strategies yet. Create one or seed the S1–S4 baselines.
        </p>
      ) : (
        // `table-fixed` + an explicit column layout keeps the 22rem-sidebar table
        // inside its card: the name column truncates instead of pushing the status
        // pill past the boundary (issue #79). Entry Z is dropped here — it's shown
        // in the detail panel — to buy the name column more room.
        <table className="w-full table-fixed text-sm" data-testid="strategy-list">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
              <th className="w-7 px-1.5 py-2 text-left">#</th>
              <th className="px-1.5 py-2 text-left">Strategy</th>
              <th className="w-20 px-1.5 py-2 text-right">Net P&amp;L</th>
              <th className="w-24 px-1.5 py-2 text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr
                key={s.id}
                onClick={() => onSelect(s.id)}
                data-testid="strategy-row"
                className={`cursor-pointer border-b border-border/50 transition-colors ${
                  selectedId === s.id ? "bg-blue/10" : "hover:bg-card"
                }`}
              >
                <td className="px-1.5 py-2 tabular-nums text-muted" data-testid="strategy-rank">
                  {s.rank ?? "—"}
                </td>
                <td
                  className="truncate px-1.5 py-2 font-medium text-text"
                  title={s.name}
                >
                  {s.name}
                </td>
                <td
                  className={`px-1.5 py-2 text-right tabular-nums ${
                    s.net_pnl == null ? "text-muted" : s.net_pnl >= 0 ? "text-green" : "text-red"
                  }`}
                >
                  {s.net_pnl == null ? "—" : fmtUsd(s.net_pnl)}
                </td>
                <td className="px-1.5 py-2 text-right">
                  <BacktestStatusBadge status={s.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function BacktestStatusBadge({ status }: { status: BacktestStatus }) {
  const tone =
    status === "COMPLETED"
      ? "bg-green/20 text-green"
      : status === "RUNNING"
        ? "bg-blue/20 text-blue"
        : status === "PAUSED"
          ? "bg-yellow/20 text-yellow"
          : status === "FAILED"
            ? "bg-red/20 text-red"
            : "bg-muted/20 text-muted"; // PENDING / STOPPED
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="bt-status-badge"
    >
      {status}
    </span>
  );
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
