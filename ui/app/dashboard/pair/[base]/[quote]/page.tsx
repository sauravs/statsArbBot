import Link from "next/link";
import PairCharts, { type EntryOverlay } from "@/components/PairCharts";

/** Parse a single query-param value to a finite number, else undefined. */
function parseNum(v: string | string[] | undefined): number | undefined {
  if (typeof v !== "string" || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export default function PairDetailPage({
  params,
  searchParams,
}: {
  params: { base: string; quote: string };
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const base = decodeURIComponent(params.base);
  const quote = decodeURIComponent(params.quote);

  // Optional "your entry" overlay — present only when the page is opened from a
  // recorded manual trade (the Manual Trades panel deep-links with these params).
  // Opened from the scan table there are no params, so the charts render plain.
  const entry: EntryOverlay = {
    z: parseNum(searchParams.ze),
    priceBase: parseNum(searchParams.pb),
    priceQuote: parseNum(searchParams.pq),
    spread: parseNum(searchParams.sp),
    time: parseNum(searchParams.et),
  };
  const hasEntry = Object.values(entry).some((v) => v !== undefined);

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

        {hasEntry && (
          <div
            data-testid="entry-overlay-badge"
            className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-yellow/40 bg-yellow/10 px-3 py-2 text-xs text-yellow"
          >
            <span className="font-semibold uppercase tracking-wider">
              Showing your recorded entry
            </span>
            {entry.z !== undefined && (
              <span className="tabular-nums">Z {entry.z.toFixed(3)}</span>
            )}
            {(entry.priceBase !== undefined || entry.priceQuote !== undefined) && (
              <span className="tabular-nums">
                {base} {entry.priceBase?.toFixed(2) ?? "—"} / {quote}{" "}
                {entry.priceQuote?.toFixed(2) ?? "—"}
              </span>
            )}
            {entry.spread !== undefined && (
              <span className="tabular-nums">spread {entry.spread.toFixed(2)}</span>
            )}
          </div>
        )}

        <PairCharts
          base={base}
          quote={quote}
          entry={hasEntry ? entry : undefined}
        />
      </section>
    </main>
  );
}
