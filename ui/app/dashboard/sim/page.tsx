"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import SimulationPanel from "@/components/SimulationPanel";

export default function SimulationPage() {
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
        <h2 className="mb-1 text-xl font-semibold text-text">Real-Time Simulation</h2>
        <p className="mb-6 text-sm text-muted">
          Paper-trade the live signals: each session ticks on its interval, opening
          and closing virtual positions on the same statistical engine the live bot
          uses — charging the <strong>same honest costs as the backtest</strong>:
          each leg pays its own market&rsquo;s half-spread plus size-aware market
          impact, and funding accrues from real rates.
        </p>
        <p className="mb-6 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-xs text-amber">
          A paper run is an <strong>operational rehearsal, not evidence of edge</strong>.
          At the recommended parameters the rate is ~1.8 trades/day, so a fortnight is
          ~26 trades against a per-trade standard deviation of $10.40 — a 95% band of
          roughly −$97 to +$110. Judge it on whether the plumbing, fills and funding
          behave, not on P&amp;L.
        </p>
        <SimulationPanel />
      </section>
    </main>
  );
}
