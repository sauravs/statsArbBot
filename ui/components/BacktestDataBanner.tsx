"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDataInventory, type DataInventory } from "@/lib/api";

// The synthetic demo history the backtest replays in DEMO mode (SCAN_DATA_SOURCE=
// fake): a fixed set of markets spanning the same range as the real cache so demo
// is a faithful stand-in for live data (#96). Kept in sync with
// backend/exchanges/demo.py (_ANCHOR / _N).
const DEMO_SPAN = "2024-01-01 → 2026-06-03";
const DEMO_MARKETS = 6;

// Slim one-line cached-data coverage banner under the Backtest page intro (issue
// #88), made data-source aware in #92. In LIVE mode it surfaces the real cached
// dYdX inventory; in DEMO mode it shows the synthetic demo span instead (the
// engine ignores the real cache offline, so the live numbers would mislead).
// Read-only and best-effort: a failed inventory fetch just hides the LIVE banner.
export default function BacktestDataBanner({
  source,
  reloadKey = 0,
}: {
  source?: string;
  reloadKey?: number;
}) {
  const [inv, setInv] = useState<DataInventory | null>(null);
  const [failed, setFailed] = useState(false);
  const isDemo = source === "fake";

  useEffect(() => {
    // Only the LIVE inventory is fetched; DEMO shows a static span.
    if (isDemo) return;
    setInv(null);
    setFailed(false);
    getDataInventory()
      .then(setInv)
      .catch(() => setFailed(true));
  }, [isDemo, reloadKey]);

  // DEMO mode: show the synthetic span the offline engine actually replays.
  if (isDemo) {
    return (
      <p className="mb-6 text-xs text-muted" data-testid="bt-data-banner">
        <span className="text-muted/70">Demo data:</span> {DEMO_MARKETS} synthetic
        markets · {DEMO_SPAN} · offline synthetic stand-in for live data.
      </p>
    );
  }

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
