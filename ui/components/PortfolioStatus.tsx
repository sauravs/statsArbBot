"use client";

import { type LiveTrade } from "@/lib/api";

// Portfolio summary (PRD F5.5) derived from the DB-backed trades: how many are
// open, how many closed, and the realised P&L booked from closed trades.
export default function PortfolioStatus({ trades }: { trades: LiveTrade[] }) {
  const open = trades.filter((t) => t.status === "OPEN").length;
  const closed = trades.filter((t) => t.status === "CLOSED");
  const errored = trades.filter((t) => t.status === "ERROR").length;
  const realisedPnl = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="portfolio-status">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Portfolio</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Metric label="Open" value={String(open)} testid="portfolio-open" />
        <Metric label="Closed" value={String(closed.length)} testid="portfolio-closed" />
        <Metric label="Errors" value={String(errored)} testid="portfolio-errors" />
        <Metric
          label="Realised P&L"
          value={fmtUsd(realisedPnl)}
          tone={realisedPnl >= 0 ? "green" : "red"}
          testid="portfolio-pnl"
        />
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
