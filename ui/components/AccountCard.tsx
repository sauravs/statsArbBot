"use client";

import { type LiveAccount } from "@/lib/api";

// Account snapshot (PRD F5.5) — free collateral + equity from the exchange.
// Collateral is the entry guard's gate (no new entries below USD_MIN_COLLATERAL).
export default function AccountCard({
  account,
  error,
}: {
  account: LiveAccount | null;
  error: string | null;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="account-card">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">Account</h2>
      {error ? (
        <p className="text-sm text-red" data-testid="account-error">
          {error}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <Metric
            label="Free collateral"
            value={account ? fmtUsd(account.free_collateral) : "—"}
            testid="account-collateral"
          />
          <Metric
            label="Equity"
            value={account ? fmtUsd(account.equity) : "—"}
            testid="account-equity"
          />
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  testid,
}: {
  label: string;
  value: string;
  testid: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-text" data-testid={testid}>
        {value}
      </p>
    </div>
  );
}

function fmtUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
