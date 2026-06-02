"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSystemHealth, type SystemHealth } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState(false);

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
          <button
            onClick={logout}
            className="rounded-lg border border-border px-3 py-1.5 text-muted hover:text-text hover:border-blue/60 transition-colors"
          >
            Log out
          </button>
        </div>
      </header>

      <section className="flex flex-col items-center justify-center py-32 text-center">
        <h2 className="text-xl font-semibold text-text">Dashboard</h2>
        <p className="mt-2 max-w-md text-sm text-muted">
          Foundation is live. Cointegration scan, pairs table, and trading
          surfaces arrive in the next phases.
        </p>
        {error && (
          <p className="mt-4 text-sm text-red">
            Could not reach the API. Is the backend running?
          </p>
        )}
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
