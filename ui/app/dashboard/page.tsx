"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSystemHealth, type SystemHealth } from "@/lib/api";
import ScanPanel from "@/components/ScanPanel";
import ManualTradesPanel from "@/components/ManualTradesPanel";

export default function DashboardPage() {
  const router = useRouter();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState(false);
  const [manualRefresh, setManualRefresh] = useState(0);

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
          <Link
            href="/dashboard/live"
            data-testid="nav-live"
            className="rounded-lg border border-border px-3 py-1.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
          >
            Live Bot
          </Link>
          <button
            onClick={logout}
            className="rounded-lg border border-border px-3 py-1.5 text-muted hover:text-text hover:border-blue/60 transition-colors"
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
        <ScanPanel onManualRecorded={() => setManualRefresh((n) => n + 1)} />
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
