"use client";

import { type FFSimulation, type FFStatus } from "@/lib/api";

// The list of fast-forward runs (PRD F7.3). Selecting one drives the detail view.
export default function FFSimList({
  sims,
  selectedId,
  onSelect,
}: {
  sims: FFSimulation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Runs
        <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
          {sims.length}
        </span>
      </h2>
      {sims.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted" data-testid="ff-list-empty">
          No replays yet. Create one to start.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="ff-list">
          {sims.map((s) => {
            const pnl = s.realised_pnl ?? 0;
            return (
              <li key={s.id}>
                <button
                  onClick={() => onSelect(s.id)}
                  data-testid="ff-list-row"
                  className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                    selectedId === s.id
                      ? "border-blue/60 bg-blue/10"
                      : "border-border hover:border-blue/40"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-text">
                      {s.label || `Run ${s.id.slice(0, 6)}`}
                    </span>
                    <FFStatusBadge status={s.status} />
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted">
                    {s.status === "RUNNING" ? (
                      <span className="tabular-nums" data-testid="ff-row-progress">
                        {Math.round((s.progress ?? 0) * 100)}%
                      </span>
                    ) : (
                      <span className="tabular-nums">{s.total_trades} trades</span>
                    )}
                    {s.realised_pnl != null && (
                      <span className={`tabular-nums ${pnl >= 0 ? "text-green" : "text-red"}`}>
                        {pnl >= 0 ? "+" : "−"}${Math.abs(pnl).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function FFStatusBadge({ status }: { status: FFStatus }) {
  const tone =
    status === "COMPLETED"
      ? "bg-green/20 text-green"
      : status === "RUNNING"
        ? "bg-blue/20 text-blue"
        : status === "FAILED"
          ? "bg-red/20 text-red"
          : "bg-muted/20 text-muted"; // STOPPED
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="ff-status-badge"
    >
      {status}
    </span>
  );
}
