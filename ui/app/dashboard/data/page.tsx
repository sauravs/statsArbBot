"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import DataInventoryPanel from "@/components/DataInventoryPanel";

export default function DataPage() {
  const router = useRouter();

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
        <h2 className="mb-1 text-xl font-semibold text-text">Historical Data</h2>
        <p className="mb-6 text-sm text-muted">
          The cached OHLCV &amp; funding history the scan, simulation, fast-forward,
          and backtest engines replay. Price data always comes from the dYdX mainnet
          indexer. Fetching new date ranges is coming soon.
        </p>
        <DataInventoryPanel />
      </section>
    </main>
  );
}
