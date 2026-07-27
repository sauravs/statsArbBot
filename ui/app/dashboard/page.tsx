"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSystemHealth, type SystemHealth } from "@/lib/api";
import ScanPanel from "@/components/ScanPanel";
import ManualTradesPanel from "@/components/ManualTradesPanel";
import JumpToSectionButton from "@/components/JumpToSectionButton";
import StrategyThresholdsControl from "@/components/StrategyThresholdsControl";
import DataSourceControl from "@/components/DataSourceControl";
import ScanFloorControl from "@/components/ScanFloorControl";

export default function DashboardPage() {
  const router = useRouter();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState(false);
  const [manualRefresh, setManualRefresh] = useState(0);
  // Bumped when the data source switches → ScanPanel reloads (pairs were cleared).
  const [dataSourceKey, setDataSourceKey] = useState(0);

  useEffect(() => {
    getSystemHealth()
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  const dbConnected = health?.database === "connected";

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📊</span>
          <h1 className="text-lg font-bold tracking-tight">statsArbBot</h1>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <StatusDot
            label="API"
            ok={!!health && !error}
            unknown={!health && !error}
          />
          <StatusDot label="DB" ok={dbConnected} unknown={!health && !error} />
          {/* Active page → highlighted (this nav lives only on the dashboard). */}
          <Link
            href="/dashboard"
            data-testid="nav-manual"
            aria-current="page"
            className="rounded-lg whitespace-nowrap border border-blue/60 bg-blue/10 px-3 py-1.5 font-medium text-text transition-colors"
          >
            Manual Trading
          </Link>
          <Link
            href="/dashboard/backtest"
            data-testid="nav-backtest"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Backtest
          </Link>
          <Link
            href="/dashboard/data"
            data-testid="nav-data"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Data
          </Link>
          {/* Fast-Forward / Simulation / Live Bot are functional but not yet
              user-tested — marked non-operational (dashed amber + dot) until a later
              phase. They still navigate normally. */}
          <Link
            href="/dashboard/ff"
            data-testid="nav-ff"
            title="Non-operational — not yet tested"
            className="rounded-lg whitespace-nowrap border border-dashed border-yellow/50 px-3 py-1.5 text-muted transition-colors hover:border-yellow hover:text-text"
          >
            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-yellow align-middle" />
            Fast-Forward
          </Link>
          <Link
            href="/dashboard/sim"
            data-testid="nav-sim"
            title="Non-operational — not yet tested"
            className="rounded-lg whitespace-nowrap border border-dashed border-yellow/50 px-3 py-1.5 text-muted transition-colors hover:border-yellow hover:text-text"
          >
            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-yellow align-middle" />
            Simulation
          </Link>
          <Link
            href="/dashboard/live"
            data-testid="nav-live"
            title="Non-operational — not yet tested"
            className="rounded-lg whitespace-nowrap border border-dashed border-yellow/50 px-3 py-1.5 text-muted transition-colors hover:border-yellow hover:text-text"
          >
            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-yellow align-middle" />
            Live Bot
          </Link>
          {/* Guide → the plain-English trading concepts doc, rendered in-app.
              Fully operational (read-only docs), so no non-operational marker. */}
          <Link
            href="/dashboard/guide"
            data-testid="nav-guide"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Guide
          </Link>
          <button
            onClick={logout}
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted hover:text-text hover:border-blue/60 transition-colors"
          >
            Log out
          </button>
        </div>
      </header>

      {/* Wide container (issue #53) so the Cointegrated Pairs table — incl. the
          Record/Action column — fits on a maximised window without horizontal
          scroll. The table keeps overflow-x-auto as the fallback for very narrow
          windows. */}
      <section className="mx-auto max-w-screen-2xl px-6 py-8">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold text-text">Manual Trading</h2>
          {/* Section-scoped controls: the Option-B strategy thresholds and the
              market-data source. Each sits in its own bordered chip with its
              label stacked above the control, so it's unambiguous which label
              owns which control (they used to run together on one line). */}
          <div className="flex flex-wrap items-stretch gap-3">
            <div
              className="flex flex-col gap-1 rounded-lg border border-border px-3 py-1.5"
              data-testid="strategy-thresholds"
            >
              <span className="text-[10px] uppercase tracking-wider text-muted">
                Z thresholds
              </span>
              <div className="flex items-center text-xs">
                <StrategyThresholdsControl
                  onApplied={() => {
                    // The chart reads thresholds from its pair-series payload, so a
                    // fresh detail view reflects them; nothing on the dashboard to
                    // refresh, but bump the key for parity with the data-source flow.
                    setDataSourceKey((k) => k + 1);
                  }}
                />
              </div>
            </div>
            <div
              className="flex flex-col gap-1 rounded-lg border border-border px-3 py-1.5"
              data-testid="market-data-control"
            >
              <span className="text-[10px] uppercase tracking-wider text-muted">
                Market data
              </span>
              <div className="flex items-center text-xs">
                <DataSourceControl
                  source={health?.data_source}
                  onSwitched={(next) => {
                    setHealth((h) => (h ? { ...h, data_source: next } : h));
                    setDataSourceKey((k) => k + 1);
                    // Manual trades are now filtered by source → re-fetch so the
                    // other source's trades drop out of the view immediately.
                    setManualRefresh((n) => n + 1);
                  }}
                />
              </div>
            </div>
            <div
              className="flex flex-col gap-1 rounded-lg border border-border px-3 py-1.5"
              data-testid="scan-floor-control"
            >
              <span className="text-[10px] uppercase tracking-wider text-muted">
                Scan floor
              </span>
              <div className="flex items-center text-xs">
                <ScanFloorControl
                  floor={health?.scan_floor}
                  onApplied={(next) => {
                    setHealth((h) => (h ? { ...h, scan_floor: next } : h));
                  }}
                />
              </div>
            </div>
          </div>
        </div>
        {error && (
          <p className="mb-4 text-sm text-red">
            Could not reach the API. Is the backend running?
          </p>
        )}
        <ScanPanel
          reloadKey={dataSourceKey}
          onManualRecorded={() => setManualRefresh((n) => n + 1)}
        />
        <ManualTradesPanel refreshKey={manualRefresh} />
      </section>
      {/* Floating shortcut: with many markets the pairs table pushes Manual
          Trades far down — this hops straight there (and back to the top). */}
      <JumpToSectionButton targetId="manual-trades-section" />
    </main>
  );
}

function StatusDot({
  label,
  ok,
  unknown,
}: {
  label: string;
  ok: boolean;
  unknown: boolean;
}) {
  const color = unknown ? "bg-yellow" : ok ? "bg-green" : "bg-red";
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
