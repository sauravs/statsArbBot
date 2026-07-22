"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSystemHealth, type SystemHealth } from "@/lib/api";
import BacktestPanel from "@/components/BacktestPanel";
import BacktestDataBanner from "@/components/BacktestDataBanner";
import DataSourceControl from "@/components/DataSourceControl";

export default function BacktestPage() {
  const router = useRouter();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  // Bumped on a data-source switch so the coverage banner re-reads for the new mode.
  const [sourceKey, setSourceKey] = useState(0);

  useEffect(() => {
    getSystemHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📊</span>
          <h1 className="text-lg font-bold tracking-tight">statsArbBot</h1>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <Link
            href="/dashboard"
            className="rounded-lg border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            ← Dashboard
          </Link>
          <button
            onClick={logout}
            className="rounded-lg border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Log out
          </button>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold text-text">Walk-Forward Backtest</h2>
          {/* Which market-data source the backtest replays — DEMO (synthetic, tiny
              span) vs LIVE (the cached dYdX history). Mirrors the dashboard's
              control so the operator can see/switch the mode here too (#92). */}
          <div
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5"
            data-testid="bt-market-data-control"
          >
            <span className="text-[10px] uppercase tracking-wider text-muted">
              Market data
            </span>
            <DataSourceControl
              source={health?.data_source}
              onSwitched={(next) => {
                setHealth((h) => (h ? { ...h, data_source: next } : h));
                setSourceKey((k) => k + 1);
              }}
            />
          </div>
        </div>
        <p className="mb-2 text-sm text-muted">
          Backtest a strategy across sliding scan/trade windows: each window re-runs
          the cointegration scan to select pairs, then trades them out-of-sample
          through the same statistical engine the live bot uses. Each run gets an equity
          curve, a per-window breakdown, and a report.
        </p>
        {/* The list used to be a net-P&L leaderboard, which made in-sample and zero-cost
            runs look like peers of tradeable ones (docs/QA.md 2026-07-22). Say plainly
            what the grouping is for. */}
        <p className="mb-2 text-sm text-muted">
          Runs are grouped by the experiment they belong to rather than ranked: a net-P&amp;L
          ranking hides the two things that decide whether a number means anything — whether
          the costs were realistic, and whether the span was one the parameters had already
          been tuned on. Both are badged on every row.
        </p>
        <BacktestDataBanner source={health?.data_source} reloadKey={sourceKey} />
        <BacktestPanel reloadKey={sourceKey} />
      </section>
    </main>
  );
}
