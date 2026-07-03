"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { PairRecord } from "@/lib/api";
import InfoTip from "./InfoTip";

type SortKey =
  | "pair"
  | "hedge_ratio"
  | "half_life"
  | "z_score"
  | "zero_crossings"
  | "p_value";

interface Props {
  pairs: PairRecord[];
  threshold: number;
  /** Current price (latest close) per market; missing markets render "—". */
  prices?: Record<string, number>;
  onRecord?: (pair: PairRecord) => void;
  /** True when a scan-time triage filter hid pairs (#150) — picks the empty state. */
  filterActive?: boolean;
}

function isActive(z: number | null, threshold: number): boolean {
  return z !== null && !Number.isNaN(z) && Math.abs(z) >= threshold;
}

function signal(
  z: number | null,
  threshold: number,
): { label: string; className: string } {
  if (z === null || Number.isNaN(z))
    return { label: "—", className: "text-muted" };
  // Market-neutral: the quote leg is always the opposite of the base leg.
  if (z >= threshold)
    return { label: "SELL base · BUY quote", className: "text-red" };
  if (z <= -threshold)
    return { label: "BUY base · SELL quote", className: "text-green" };
  return { label: "Neutral", className: "text-muted" };
}

function num(v: number | null, digits = 2): string {
  return v === null || Number.isNaN(v) ? "—" : v.toFixed(digits);
}

// Medium-length explanations for the ⓘ tooltips (issue #49), grounded in the
// domain glossary (CONTEXT.md).
const TIPS = {
  pair: "The two markets traded together: base (leg 1) and quote (leg 2). Click the row to open its 3-panel charts.",
  hedge:
    "Hedge ratio β — how many units of the quote leg offset one unit of the base leg to make the position market-neutral (the OLS slope of base vs. quote).",
  halfLife:
    "Average time, in hours, for the spread to revert halfway to its mean. Shorter = faster reversion. Pairs are kept only when it's between 0 and 72h.",
  zScore:
    "How far the current spread sits from its recent mean, in standard deviations. The live signal — a large |Z| means the gap is abnormally wide and likely to revert.",
  zeroX:
    "Zero-crossings: how many times the spread crossed its mean in the formation window. More crossings = more reliably mean-reverting (a quality proxy).",
  pValue:
    "Engle-Granger cointegration test p-value. Lower means stronger evidence the two markets move together over the long run (typically kept below 0.05).",
  price:
    "Current price of each leg — the latest hourly close of the base and quote markets (base / quote).",
  signal:
    "When the pair is active (|Z| ≥ threshold), the market-neutral action: which leg to sell and which to buy. The two legs are always opposite.",
  action:
    "Record this trade: capture both legs' capital and entry prices to the Manual Trades log for a close/P&L lifecycle.",
} as const;

export default function PairsTable({
  pairs,
  threshold,
  prices = {},
  onRecord,
  filterActive = false,
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("zero_crossings");
  const [asc, setAsc] = useState(false);

  const sorted = useMemo(() => {
    const rows = [...pairs];
    rows.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (sortKey === "pair") {
        av = `${a.base_market}/${a.quote_market}`;
        bv = `${b.base_market}/${b.quote_market}`;
      } else {
        av = a[sortKey] ?? Number.NEGATIVE_INFINITY;
        bv = b[sortKey] ?? Number.NEGATIVE_INFINITY;
      }
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    return rows;
  }, [pairs, sortKey, asc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(false);
    }
  }

  if (pairs.length === 0) {
    // A triage filter that hid every pair gets its own message (loosen the
    // filter), distinct from "no pairs scanned yet" (run a scan) — #150.
    if (filterActive) {
      return (
        <p
          className="py-10 text-center text-sm text-muted"
          data-testid="pairs-empty-filtered"
        >
          No pairs meet the p-value / half-life filter. Loosen the values above.
        </p>
      );
    }
    return (
      <p className="py-10 text-center text-sm text-muted" data-testid="pairs-empty">
        No cointegrated pairs yet. Run a scan to populate the table.
      </p>
    );
  }

  // Shorter labels (base/quote + units explained in the ⓘ tooltips) so the
  // whole table fits one view without a horizontal scroll (issue #48).
  const headers: { key: SortKey; label: string; align: string; tip: string }[] =
    [
      { key: "pair", label: "Pair", align: "text-left", tip: TIPS.pair },
      { key: "hedge_ratio", label: "Hedge β", align: "text-right", tip: TIPS.hedge },
      { key: "half_life", label: "Half-life", align: "text-right", tip: TIPS.halfLife },
      { key: "z_score", label: "Z-score", align: "text-right", tip: TIPS.zScore },
      { key: "zero_crossings", label: "Zero-x", align: "text-right", tip: TIPS.zeroX },
      { key: "p_value", label: "p-value", align: "text-right", tip: TIPS.pValue },
    ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="pairs-table">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
            {headers.map((h) => (
              <th
                key={h.key}
                className={`${h.align} select-none whitespace-nowrap px-2 py-2`}
              >
                <span
                  onClick={() => toggleSort(h.key)}
                  className="cursor-pointer hover:text-text"
                >
                  {h.label}
                  {sortKey === h.key && (asc ? " ↑" : " ↓")}
                </span>
                <InfoTip text={h.tip} />
              </th>
            ))}
            <th className="whitespace-nowrap px-2 py-2 text-right">
              Price<InfoTip text={TIPS.price} />
            </th>
            <th className="whitespace-nowrap px-2 py-2 text-right">
              Signal<InfoTip text={TIPS.signal} />
            </th>
            <th className="whitespace-nowrap px-2 py-2 text-right">
              Action<InfoTip text={TIPS.action} />
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => {
            const sig = signal(p.z_score, threshold);
            const href = `/dashboard/pair/${encodeURIComponent(p.base_market)}/${encodeURIComponent(p.quote_market)}`;
            return (
              <tr
                key={`${p.base_market}-${p.quote_market}`}
                className="border-b border-border/50 hover:bg-bg/40"
                data-testid="pair-row"
              >
                <td className="whitespace-nowrap px-2 py-2 font-medium">
                  <Link
                    href={href}
                    className="text-text hover:text-blue hover:underline"
                    data-testid="pair-link"
                  >
                    {p.base_market}
                    <span className="text-muted"> / {p.quote_market}</span>
                  </Link>
                  <Link
                    href={href}
                    title="Open 3-panel charts"
                    aria-label="Open charts"
                    data-testid="pair-charts-link"
                    className="ml-1.5 font-normal text-blue hover:underline"
                  >
                    ›
                  </Link>
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {num(p.hedge_ratio, 4)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {num(p.half_life, 1)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {num(p.z_score, 3)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {p.zero_crossings}
                </td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {num(p.p_value, 4)}
                </td>
                <td
                  className="whitespace-nowrap px-2 py-2 text-right tabular-nums text-muted"
                  data-testid="pair-price"
                >
                  {num(prices[p.base_market] ?? null, 2)}
                  {" / "}
                  {num(prices[p.quote_market] ?? null, 2)}
                </td>
                <td
                  className={`whitespace-nowrap px-2 py-2 text-right font-medium ${sig.className}`}
                >
                  {sig.label}
                </td>
                <td className="px-2 py-2 text-right">
                  {isActive(p.z_score, threshold) && onRecord ? (
                    <button
                      onClick={() => onRecord(p)}
                      data-testid="record-trade-btn"
                      className="rounded border border-green px-2 py-1 text-xs text-green transition hover:bg-green/10"
                    >
                      Record
                    </button>
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
