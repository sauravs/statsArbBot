"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDataInventory, type DataInventory } from "@/lib/api";

// Slim one-line cached-data coverage banner under the Backtest page intro (issue
// #88). It surfaces what the Data section already knows — markets, date range,
// bars, funding — so the operator can pick a valid Start/End and set expectations
// before running, without leaving the Backtest page. Read-only and best-effort: a
// failed inventory fetch just hides the banner rather than blocking the page.
export default function BacktestDataBanner() {
  const [inv, setInv] = useState<DataInventory | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getDataInventory()
      .then(setInv)
      .catch(() => setFailed(true));
  }, []);

  if (failed) return null;

  const s = inv?.summary;
  return (
    <p className="mb-6 text-xs text-muted" data-testid="bt-data-banner">
      <span className="text-muted/70">Cached data:</span>{" "}
      {!s ? (
        <span className="text-muted/50">—</span>
      ) : (
        <>
          {s.market_count} markets ·{" "}
          {s.earliest && s.latest
            ? `${s.earliest.slice(0, 10)} → ${s.latest.slice(0, 10)}`
            : "no range"}{" "}
          · {s.total_bars.toLocaleString()} bars · funding {s.funding_markets} mkts
        </>
      )}
      {" · "}
      <Link href="/dashboard/data" className="text-blue hover:underline">
        Data ↗
      </Link>
    </p>
  );
}
