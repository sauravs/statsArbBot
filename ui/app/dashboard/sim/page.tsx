"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import SimulationPanel from "@/components/SimulationPanel";
import NonOperationalBanner from "@/components/NonOperationalBanner";

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
          uses, with a slippage / fee / funding cost model.
        </p>
        <NonOperationalBanner section="Real-Time Simulation" />
        <SimulationPanel />
      </section>
    </main>
  );
}
