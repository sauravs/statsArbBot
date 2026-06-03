"use client";

import { type SimSession, type SimStatus } from "@/lib/api";

// The list of simulation sessions (PRD F6.5). Selecting one drives the detail view.
export default function SimSessionList({
  sessions,
  selectedId,
  onSelect,
}: {
  sessions: SimSession[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Sessions
        <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
          {sessions.length}
        </span>
      </h2>
      {sessions.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted" data-testid="sim-list-empty">
          No simulations yet. Create one to start paper trading.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="sim-list">
          {sessions.map((s) => {
            const pnl = s.current_capital - s.starting_capital;
            return (
              <li key={s.id}>
                <button
                  onClick={() => onSelect(s.id)}
                  data-testid="sim-list-row"
                  className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                    selectedId === s.id
                      ? "border-blue/60 bg-blue/10"
                      : "border-border hover:border-blue/40"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-text">
                      {s.label || `Sim ${s.id.slice(0, 6)}`}
                    </span>
                    <StatusBadge status={s.status} />
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted">
                    <span className="tabular-nums">
                      ${s.current_capital.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </span>
                    <span className={`tabular-nums ${pnl >= 0 ? "text-green" : "text-red"}`}>
                      {pnl >= 0 ? "+" : "−"}${Math.abs(pnl).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </span>
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

export function StatusBadge({ status }: { status: SimStatus }) {
  const tone =
    status === "RUNNING"
      ? "bg-green/20 text-green"
      : status === "PAUSED"
        ? "bg-yellow/20 text-yellow"
        : "bg-muted/20 text-muted";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="sim-status-badge"
    >
      {status}
    </span>
  );
}
