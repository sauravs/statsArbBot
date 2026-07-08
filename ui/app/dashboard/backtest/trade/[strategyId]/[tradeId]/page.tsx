import Link from "next/link";
import BacktestTradeChart from "@/components/BacktestTradeChart";

// Per-trade chart page (issue #166): the four pair panels over a backtest trade's
// test window, with the trade's own entry/exit marked. Opened in a new tab from the
// "Chart" column of the walk-forward trade blotter.
export default function BacktestTradeChartPage({
  params,
}: {
  params: { strategyId: string; tradeId: string };
}) {
  const strategyId = decodeURIComponent(params.strategyId);
  const tradeId = decodeURIComponent(params.tradeId);

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard/backtest"
            className="text-sm text-muted hover:text-text"
            data-testid="back-to-backtest"
          >
            ← Backtest
          </Link>
          <h1 className="text-lg font-bold tracking-tight">Trade chart</h1>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-8">
        <BacktestTradeChart strategyId={strategyId} tradeId={tradeId} />
      </section>
    </main>
  );
}
