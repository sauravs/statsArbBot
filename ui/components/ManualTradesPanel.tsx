"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  getManualPortfolio,
  getManualTrades,
  type ManualPortfolio,
  type ManualTrade,
} from "@/lib/api";
import CloseManualTradeModal from "./CloseManualTradeModal";
import DeleteManualTradeModal from "./DeleteManualTradeModal";
import InfoTip from "./InfoTip";

// Mark-to-market refreshes on a slow interval so a real dydx-mode price fetch
// stays cheap (issue #37 PR-2).
const PORTFOLIO_POLL_MS = 20000;

function usd(v: number): string {
  return `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
}

// Deep-link to the pair's chart page carrying this trade's entry context, so the
// charts can overlay the entry Z, entry prices, entry spread, and entry moment.
// Values ride in the URL (read back by PairCharts' `entry` prop) — no extra fetch,
// and it keeps working even after a data-source switch filters the trades list.
function chartHref(t: ManualTrade): string {
  const params = new URLSearchParams({
    ze: String(t.z_score),
    pb: String(t.entry_price_leg1),
    pq: String(t.entry_price_leg2),
    sp: String(t.spread_value),
    et: String(Math.floor(new Date(t.recorded_at).getTime() / 1000)),
  });
  return `/dashboard/pair/${encodeURIComponent(t.base_market)}/${encodeURIComponent(t.quote_market)}?${params.toString()}`;
}

// Separate "Manual Trades" section (PRD F4.6) — not mixed with bot trades.
// Lists recorded trades with their lifecycle: OPEN trades can be marked closed
// (P&L computed), CLOSED trades show realised P&L.
export default function ManualTradesPanel({
  refreshKey,
}: {
  refreshKey: number;
}) {
  const [trades, setTrades] = useState<ManualTrade[]>([]);
  const [portfolio, setPortfolio] = useState<ManualPortfolio | null>(null);
  // The live mark-to-market (Unrealized P&L) is the only summary figure that
  // needs a live price fetch — slow against the dydx indexer right after a
  // scan/record (issue #60). Track its load so the card can render instantly
  // (with the cheap figures derived below) and show a spinner just for it.
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<ManualTrade | null>(null);
  const [deleting, setDeleting] = useState<ManualTrade | null>(null);

  // Best-effort mark-to-market; a failure keeps the last summary.
  const refreshPortfolio = useCallback(async () => {
    setPortfolioLoading(true);
    try {
      setPortfolio(await getManualPortfolio());
    } catch {
      /* keep previous summary */
    } finally {
      setPortfolioLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const res = await getManualTrades();
      setTrades(res.trades);
      setError(res.error ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load manual trades");
    }
    await refreshPortfolio();
  }, [refreshPortfolio]);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  // Slow, independent mark-to-market refresh.
  useEffect(() => {
    const id = setInterval(refreshPortfolio, PORTFOLIO_POLL_MS);
    return () => clearInterval(id);
  }, [refreshPortfolio]);

  // Allocated / Realized / counts are derived straight from the trades list (a
  // fast DB read) so the summary card renders immediately — only the live
  // mark-to-market below waits on the indexer (issue #60).
  const openTrades = trades.filter((t) => t.status === "OPEN");
  const closedTrades = trades.filter((t) => t.status === "CLOSED");
  const allocated = openTrades.reduce(
    (s, t) => s + t.capital_leg1_usd + t.capital_leg2_usd,
    0,
  );
  const realized = closedTrades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const openCount = openTrades.length;
  const closedCount = closedTrades.length;

  // Unrealized P&L needs the live price fetch: show a spinner while it resolves
  // (open trades, not yet priced), the value once it lands, or "—" if there's
  // nothing to mark / pricing failed.
  const unrealizedPending =
    openCount > 0 &&
    portfolio?.unrealized_pnl == null &&
    (portfolioLoading || portfolio == null);

  return (
    <div className="mt-6 rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted">
          Manual Trades
          <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
            {trades.length}
          </span>
        </h2>
      </div>

      {trades.length > 0 && (
        <div
          className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4"
          data-testid="portfolio-summary"
        >
          <SummaryStat
            label="Allocated (open)"
            tip="Total capital committed across OPEN manual trades — the sum of both legs' capital for every open position."
            value={usd(allocated)}
            testid="portfolio-allocated"
          />
          <SummaryStat
            label="Unrealized P&L"
            tip="Live mark-to-market profit/loss on OPEN trades: each leg valued at its current price as if closed now. Updates as prices move."
            value={
              unrealizedPending
                ? null
                : portfolio?.unrealized_pnl == null
                  ? "—"
                  : usd(portfolio.unrealized_pnl)
            }
            loading={unrealizedPending}
            tone={
              portfolio?.unrealized_pnl == null
                ? "muted"
                : portfolio.unrealized_pnl >= 0
                  ? "green"
                  : "red"
            }
            testid="portfolio-unrealized"
          />
          <SummaryStat
            label="Realized P&L"
            tip="Booked profit/loss from CLOSED trades — the sum of each closed trade's final per-leg P&L."
            value={usd(realized)}
            tone={realized >= 0 ? "green" : "red"}
            testid="portfolio-realized"
          />
          <SummaryStat
            label="Open / Closed"
            tip="Count of manual trades currently open vs. already closed (for the active data source)."
            value={`${openCount} / ${closedCount}`}
            testid="portfolio-counts"
          />
        </div>
      )}

      {error && <p className="mb-3 text-sm text-red">{error}</p>}

      {trades.length === 0 ? (
        <p
          className="py-8 text-center text-sm text-muted"
          data-testid="manual-empty"
        >
          No manual trades recorded yet. Set the Z-threshold, then record a trade
          from an active-signal pair.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="manual-table">
            <thead>
              <tr className="whitespace-nowrap border-b border-border text-xs uppercase tracking-wider text-muted">
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-right">Z @ entry</th>
                <th className="px-3 py-2 text-right">Capital (1 / 2)</th>
                <th className="px-3 py-2 text-right">Entry (1 / 2)</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">Status</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr
                  key={t.id}
                  className="whitespace-nowrap border-b border-border/50"
                  data-testid="manual-row"
                >
                  <td className="whitespace-nowrap px-3 py-2 font-medium">
                    <Link
                      href={chartHref(t)}
                      className="text-text hover:text-blue hover:underline"
                      data-testid="manual-pair-link"
                    >
                      {t.base_market}
                      <span className="text-muted"> / {t.quote_market}</span>
                    </Link>
                    <Link
                      href={chartHref(t)}
                      title="Open charts with your entry marked"
                      aria-label="Open charts"
                      data-testid="manual-charts-link"
                      className="ml-1.5 font-normal text-blue hover:underline"
                    >
                      ›
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {t.z_score.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.capital_leg1_usd.toFixed(0)} / {t.capital_leg2_usd.toFixed(0)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {t.entry_price_leg1.toFixed(2)} / {t.entry_price_leg2.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${
                      t.pnl == null
                        ? "text-muted"
                        : t.pnl >= 0
                          ? "text-green"
                          : "text-red"
                    }`}
                    data-testid="manual-pnl"
                  >
                    {t.pnl == null ? "—" : t.pnl.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        t.status === "OPEN"
                          ? "bg-blue/20 text-blue"
                          : "bg-muted/20 text-muted"
                      }`}
                      data-testid="manual-status"
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-2">
                      {t.status === "OPEN" && (
                        <button
                          onClick={() => setClosing(t)}
                          data-testid="close-trade-btn"
                          className="rounded border border-yellow px-2 py-1 text-xs text-yellow hover:bg-yellow/10"
                        >
                          Mark closed
                        </button>
                      )}
                      <button
                        onClick={() => setDeleting(t)}
                        data-testid="delete-trade-btn"
                        className="rounded border border-red px-2 py-1 text-xs text-red hover:bg-red/10"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {closing && (
        <CloseManualTradeModal
          trade={closing}
          onClose={() => setClosing(null)}
          onClosed={refresh}
        />
      )}

      {deleting && (
        <DeleteManualTradeModal
          trade={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={refresh}
        />
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone = "default",
  testid,
  tip,
  loading = false,
}: {
  label: string;
  value: string | null;
  tone?: "default" | "green" | "red" | "muted";
  testid: string;
  tip?: string;
  loading?: boolean;
}) {
  const valueColor =
    tone === "green"
      ? "text-green"
      : tone === "red"
        ? "text-red"
        : tone === "muted"
          ? "text-muted"
          : "text-text";
  return (
    <div className="rounded-lg border border-border bg-bg/40 px-3 py-2">
      <div className="text-xs uppercase tracking-wider text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </div>
      <div
        className={`mt-0.5 text-lg font-semibold tabular-nums ${valueColor}`}
        data-testid={testid}
      >
        {loading ? (
          <span className="flex items-center gap-1.5 text-sm text-muted">
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted/30 border-t-muted" />
            computing…
          </span>
        ) : (
          value
        )}
      </div>
    </div>
  );
}
