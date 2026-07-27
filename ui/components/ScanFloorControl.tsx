"use client";

import { useState } from "react";
import { setScanFloor } from "@/lib/api";
import InfoTip from "./InfoTip";

// Live/manual-scan liquidity floor control (WS1). Sets the app-wide 24h-$ floor
// that both exchange clients apply when listing markets, so the scan/manual pair
// list only surfaces names above it. Runtime-settable (mirrors DataSourceControl);
// resets to the env default on restart.
//
// FRAMING (critical, docs/PHASE2_STRATEGY_PLAN.md §4/§5): this is a
// TRACTABILITY/executability knob — raising it shrinks the pair list
// super-linearly (the scan pairs markets, ~N²/2) to a reviewable, fillable set.
// It is NOT an alpha lever: the §4 "deciding experiment" showed filtering up
// LOSES money (the gross lives in the thinnest markets). See docs/QA.md.
const NOTE =
  "Tractability knob, not a profit lever: raising the floor shrinks the " +
  "scan/manual pair list to a reviewable, fillable size. It does NOT create " +
  "edge — filtering up to liquid names loses money (the gross lives in the " +
  "thinnest markets). See docs/QA.md (WS1 scan-floor entry). Resets on restart.";

// Compact preset shortcuts matching the documented survivor counts
// (docs/PHASE2_STRATEGY_PLAN.md §5 / strategy.md Slice 0): $1M ≈ 48 markets.
const PRESETS: { label: string; value: number }[] = [
  { label: "Off", value: 0 },
  { label: "$100k", value: 100_000 },
  { label: "$1M", value: 1_000_000 },
  { label: "$5M", value: 5_000_000 },
  { label: "$20M", value: 20_000_000 },
];

function formatUsd(v: number): string {
  if (v <= 0) return "Off";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toLocaleString()}M`;
  if (v >= 1_000) return `$${(v / 1_000).toLocaleString()}k`;
  return `$${v.toLocaleString()}`;
}

export default function ScanFloorControl({
  floor,
  onApplied,
}: {
  floor?: number;
  onApplied: (next: number) => void;
}) {
  // Draft the input as a string so the field can be emptied mid-edit.
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (floor === undefined) {
    return (
      <span
        data-testid="scan-floor-badge"
        className="rounded-full bg-muted/20 px-2 py-0.5 text-xs font-medium text-muted"
      >
        …
      </span>
    );
  }

  const parsed = draft === null ? floor : Number(draft);
  const dirty =
    draft !== null && draft.trim() !== "" && Number.isFinite(parsed) && parsed !== floor;

  async function apply(value: number) {
    setBusy(true);
    setErr(null);
    try {
      const res = await setScanFloor(value);
      onApplied(res.min_liquidity_usd);
      setDraft(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center gap-1.5">
      <span
        data-testid="scan-floor-badge"
        title={`Live/manual scan liquidity floor: ${formatUsd(floor)}/24h`}
        className="rounded-full bg-blue/20 px-2 py-0.5 text-xs font-medium text-blue"
      >
        {formatUsd(floor)}
      </span>

      {busy ? (
        <span
          className="flex items-center gap-1.5 text-blue"
          data-testid="scan-floor-applying"
        >
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue/30 border-t-blue" />
          Applying…
        </span>
      ) : (
        <span className="flex items-center gap-1">
          <input
            type="number"
            min={0}
            step={100_000}
            data-testid="scan-floor-input"
            aria-label="Scan liquidity floor (24h USD)"
            value={draft ?? String(floor)}
            onChange={(e) => {
              setErr(null);
              setDraft(e.target.value);
            }}
            className="w-24 rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-text transition-colors hover:border-blue/60"
          />
          {dirty && (
            <button
              onClick={() => apply(parsed)}
              data-testid="scan-floor-apply"
              title="Apply the scan floor — takes effect on the next scan."
              className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
            >
              Apply
            </button>
          )}
        </span>
      )}

      <span className="flex items-center gap-0.5" data-testid="scan-floor-presets">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => apply(p.value)}
            disabled={busy || p.value === floor}
            className="rounded border border-border px-1 py-0.5 text-[10px] text-muted hover:border-blue/60 hover:text-text disabled:opacity-40"
          >
            {p.label}
          </button>
        ))}
      </span>

      <InfoTip text={NOTE} />
      {err && (
        <span className="text-red" data-testid="scan-floor-error">
          {err}
        </span>
      )}
    </span>
  );
}
