"use client";

import { useState } from "react";
import { setDataSource } from "@/lib/api";

// Venue / market-data source selector (issues #42 / #43; extended to Hyperliquid
// on the `hyperliquid` branch, Slice 5). Sets the app-wide market-data source; the
// whole stack — scan, Backtest, Manual Trading — then follows the selected venue
// (the backend resolves the active exchange from this source). "Demo" is the
// network-free synthetic source; dYdX / Hyperliquid are live read-only data.
//
// Switching is a deliberate two-step (select → Switch) because it clears the
// current pairs (they belong to the old source) → a re-scan is prompted.
const SOURCES: { id: string; label: string; live: boolean }[] = [
  { id: "fake", label: "Demo", live: false },
  { id: "dydx", label: "dYdX", live: true },
  { id: "hyperliquid", label: "Hyperliquid", live: true },
];

export default function DataSourceControl({
  source,
  onSwitched,
}: {
  source?: string;
  onSwitched: (next: string) => void;
}) {
  const [pending, setPending] = useState<string | null>(null);
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

  const current = SOURCES.find((s) => s.id === source);
  const isDemo = !current?.live;
  // Fake → "DEMO DATA" (kept stable for #42 E2E); a live venue → "<VENUE> LIVE".
  const badgeText = isDemo
    ? "DEMO DATA"
    : `${(current?.label ?? source).toUpperCase()} LIVE`;

  async function doSwitch(target: string) {
    setBusy(true);
    setErr(null);
    try {
      const res = await setDataSource(target);
      onSwitched(res.data_source);
      setPending(null);
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
            : `Live ${current?.label} market data`
        }
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
          isDemo ? "bg-yellow/20 text-yellow" : "bg-green/20 text-green"
        }`}
      >
        {badgeText}
      </span>

      {busy ? (
        // Clear in-progress state so a slow switch never reads as a frozen UI (#67).
        <span
          className="flex items-center gap-1.5 text-blue"
          data-testid="data-source-switching"
        >
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue/30 border-t-blue" />
          Switching…
        </span>
      ) : (
        <span className="flex items-center gap-1">
          <select
            data-testid="data-source-select"
            aria-label="Market-data venue"
            value={pending ?? source}
            onChange={(e) => {
              const v = e.target.value;
              setErr(null);
              setPending(v === source ? null : v);
            }}
            className="rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-text transition-colors hover:border-blue/60"
          >
            {SOURCES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          {pending && pending !== source && (
            <button
              onClick={() => doSwitch(pending)}
              data-testid="data-source-confirm"
              title="Switch venue — clears the current pairs; re-scan after."
              className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
            >
              Switch
            </button>
          )}
        </span>
      )}
      {err && <span className="text-red">{err}</span>}
    </span>
  );
}
