"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { PairRecord } from "@/lib/api";

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
  onRecord?: (pair: PairRecord) => void;
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

export default function PairsTable({ pairs, threshold, onRecord }: Props) {
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
    return (
      <p className="py-10 text-center text-sm text-muted" data-testid="pairs-empty">
        No cointegrated pairs yet. Run a scan to populate the table.
      </p>
    );
  }

  const headers: { key: SortKey; label: string; align: string }[] = [
    { key: "pair", label: "Pair (Base / Quote)", align: "text-left" },
    { key: "hedge_ratio", label: "Hedge β", align: "text-right" },
    { key: "half_life", label: "Half-life (h)", align: "text-right" },
    { key: "z_score", label: "Z-score", align: "text-right" },
    { key: "zero_crossings", label: "Zero-x", align: "text-right" },
    { key: "p_value", label: "p-value", align: "text-right" },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="pairs-table">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
            {headers.map((h) => (
              <th
                key={h.key}
                onClick={() => toggleSort(h.key)}
                className={`${h.align} cursor-pointer select-none py-2 px-3 hover:text-text`}
              >
                {h.label}
                {sortKey === h.key && (asc ? " ↑" : " ↓")}
              </th>
            ))}
            <th className="px-3 py-2 text-right">Signal</th>
            <th className="px-3 py-2 text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => {
            const sig = signal(p.z_score, threshold);
            return (
              <tr
                key={`${p.base_market}-${p.quote_market}`}
                className="border-b border-border/50 hover:bg-bg/40"
                data-testid="pair-row"
              >
                <td className="px-3 py-2 font-medium">
                  <Link
                    href={`/dashboard/pair/${encodeURIComponent(p.base_market)}/${encodeURIComponent(p.quote_market)}`}
                    className="text-text hover:text-blue hover:underline"
                    data-testid="pair-link"
                  >
                    {p.base_market}
                    <span className="text-muted"> / {p.quote_market}</span>
                  </Link>
                  <Link
                    href={`/dashboard/pair/${encodeURIComponent(p.base_market)}/${encodeURIComponent(p.quote_market)}`}
                    className="ml-2 text-xs font-normal text-blue hover:underline"
                    data-testid="pair-charts-link"
                  >
                    Charts ›
                  </Link>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {num(p.hedge_ratio, 4)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {num(p.half_life, 1)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {num(p.z_score, 3)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {p.zero_crossings}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {num(p.p_value, 4)}
                </td>
                <td className={`px-3 py-2 text-right font-medium ${sig.className}`}>
                  {sig.label}
                </td>
                <td className="px-3 py-2 text-right">
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
