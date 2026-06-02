import Link from "next/link";
import PairCharts from "@/components/PairCharts";

export default function PairDetailPage({
  params,
}: {
  params: { base: string; quote: string };
}) {
  const base = decodeURIComponent(params.base);
  const quote = decodeURIComponent(params.quote);

  return (
    <main className="min-h-screen bg-bg text-text">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="text-sm text-muted hover:text-text"
            data-testid="back-to-dashboard"
          >
            ← Dashboard
          </Link>
          <h1 className="text-lg font-bold tracking-tight">
            {base}
            <span className="text-muted"> / {quote}</span>
          </h1>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-8">
        <h2 className="mb-4 text-xl font-semibold">Pair detail</h2>
        <PairCharts base={base} quote={quote} />
      </section>
    </main>
  );
}
