"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSystemHealth, setDataSource, type SystemHealth } from "@/lib/api";
import ScanPanel from "@/components/ScanPanel";
import ManualTradesPanel from "@/components/ManualTradesPanel";

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
          <DataSourceControl
            source={health?.data_source}
            onSwitched={(next) => {
              setHealth((h) => (h ? { ...h, data_source: next } : h));
              setDataSourceKey((k) => k + 1);
            }}
          />
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
            href="/dashboard/sim"
            data-testid="nav-sim"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Simulation
          </Link>
          <Link
            href="/dashboard/ff"
            data-testid="nav-ff"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Fast-Forward
          </Link>
          <Link
            href="/dashboard/backtest"
            data-testid="nav-backtest"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Backtest
          </Link>
          <Link
            href="/dashboard/live"
            data-testid="nav-live"
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Live Bot
          </Link>
          <button
            onClick={logout}
            className="rounded-lg whitespace-nowrap border border-border px-3 py-1.5 text-muted hover:text-text hover:border-blue/60 transition-colors"
          >
            Log out
          </button>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-8">
        <h2 className="mb-4 text-xl font-semibold text-text">Dashboard</h2>
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

// Market-data source indicator + runtime toggle (issues #42 / #43). The badge
// shows synthetic demo data vs the live dYdX indexer; the switch flips it
// app-wide without a restart (no orders — a read-only data change). Switching
// clears the current pairs (they belong to the old source) → re-scan prompted.
function DataSourceControl({
  source,
  onSwitched,
}: {
  source?: string;
  onSwitched: (next: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!source) return null;
  const isDemo = source === "fake";
  const target = isDemo ? "dydx" : "fake";
  const targetLabel = isDemo ? "Live" : "Demo";

  async function doSwitch() {
    setBusy(true);
    setErr(null);
    try {
      const res = await setDataSource(target);
      onSwitched(res.data_source);
      setConfirming(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Switch failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center gap-1.5">
      <span
        data-testid="data-source-badge"
        title={
          isDemo
            ? "Synthetic demo data (SCAN_DATA_SOURCE=fake)"
            : "Live dYdX market data"
        }
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
          isDemo ? "bg-yellow/20 text-yellow" : "bg-green/20 text-green"
        }`}
      >
        {isDemo ? "DEMO DATA" : "LIVE DATA"}
      </span>

      {confirming ? (
        <span className="flex items-center gap-1">
          <button
            onClick={doSwitch}
            disabled={busy}
            data-testid="data-source-confirm"
            title={`Switch to ${targetLabel} data — clears the current pairs; re-scan after.`}
            className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
          >
            {busy ? "…" : `Confirm ${targetLabel}`}
          </button>
          <button
            onClick={() => {
              setConfirming(false);
              setErr(null);
            }}
            disabled={busy}
            className="rounded border border-border px-1.5 py-0.5 text-muted hover:text-text"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          data-testid="data-source-toggle"
          title={`Switch the app-wide market-data source to ${targetLabel}`}
          className="rounded border border-border px-1.5 py-0.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
        >
          Use {targetLabel}
        </button>
      )}
      {err && <span className="text-red">{err}</span>}
    </span>
  );
}
