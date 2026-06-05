"use client";

import { useState } from "react";
import { setDataSource } from "@/lib/api";

// Market-data source indicator + runtime toggle (issues #42 / #43; extracted to a
// shared component in #92 so the Backtest page can show the same DEMO/LIVE control
// the dashboard header uses). The badge shows synthetic demo data vs the live dYdX
// indexer; the switch flips it app-wide without a restart (no orders — a read-only
// data change). Switching clears the current pairs (they belong to the old source)
// → a re-scan is prompted.
export default function DataSourceControl({
  source,
  onSwitched,
}: {
  source?: string;
  onSwitched: (next: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Never blank the whole control while health is (re)loading — show a neutral
  // placeholder badge so the "Market data" label/badge doesn't vanish (#67).
  if (!source) {
    return (
      <span
        data-testid="data-source-badge"
        className="rounded-full bg-muted/20 px-2 py-0.5 text-xs font-medium text-muted"
      >
        …
      </span>
    );
  }
  const isDemo = source === "fake";
  const target = isDemo ? "dydx" : "fake";
  const targetLabel = isDemo ? "Live" : "Demo";

  async function doSwitch() {
    setBusy(true);
    setErr(null);
    try {
      const res = await setDataSource(target);
      onSwitched(res.data_source);
      setConfirming(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Switch failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center gap-1.5">
      <span
        data-testid="data-source-badge"
        title={
          isDemo
            ? "Synthetic demo data (SCAN_DATA_SOURCE=fake)"
            : "Live dYdX market data"
        }
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
          isDemo ? "bg-yellow/20 text-yellow" : "bg-green/20 text-green"
        }`}
      >
        {isDemo ? "DEMO DATA" : "LIVE DATA"}
      </span>

      {busy ? (
        // Clear in-progress state so a slow switch never reads as a frozen UI (#67).
        <span
          className="flex items-center gap-1.5 text-blue"
          data-testid="data-source-switching"
        >
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue/30 border-t-blue" />
          Switching to {targetLabel}…
        </span>
      ) : confirming ? (
        <span className="flex items-center gap-1">
          <button
            onClick={doSwitch}
            data-testid="data-source-confirm"
            title={`Switch to ${targetLabel} data — clears the current pairs; re-scan after.`}
            className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
          >
            {`Confirm ${targetLabel}`}
          </button>
          <button
            onClick={() => {
              setConfirming(false);
              setErr(null);
            }}
            className="rounded border border-border px-1.5 py-0.5 text-muted hover:text-text"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          data-testid="data-source-toggle"
          title={`Switch the app-wide market-data source to ${targetLabel}`}
          className="rounded border border-border px-1.5 py-0.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
        >
          Use {targetLabel}
        </button>
      )}
      {err && <span className="text-red">{err}</span>}
    </span>
  );
}
