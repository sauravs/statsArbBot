"use client";

import { useState } from "react";
import { setScanListFilters, type ScanListFilters } from "@/lib/api";
import InfoTip from "./InfoTip";

// Read-time scan/manual-list minimisation control (Phase-3 WS2). Two runtime knobs
// applied to the pairs/manual list *after* the scan: a half-spread ceiling (drop
// pairs whose wider leg is too wide to fill cheaply) and a top-N cap by a
// tradability score (min $-vol × 1/half-life × (1−p)). Non-destructive — the stored
// scan is untouched, so adjust freely with no re-scan (mirrors ScanFloorControl).
//
// FRAMING (critical, docs/PHASE2_STRATEGY_PLAN §4/§5): a TRACTABILITY lens —
// surface a shorter, fillable shortlist — NOT an alpha lever. Filtering toward
// liquid names does not add edge (the §4 refutation). See docs/QA.md.
const NOTE =
  "Minimise the manual list to a reviewable, fillable shortlist: drop pairs whose " +
  "wider leg exceeds the half-spread ceiling, then keep the top-N by tradability " +
  "(min $-vol × 1/half-life × (1−p)). Tractability only — NOT a profit lever; " +
  "filtering toward liquid names does not add edge (see docs/QA.md). Read-time, " +
  "non-destructive, resets on restart. 0/blank = off.";

export default function ScanListFilterControl({
  filters,
  onApplied,
}: {
  filters?: ScanListFilters;
  onApplied: (next: ScanListFilters) => void;
}) {
  const [ceilDraft, setCeilDraft] = useState<string | null>(null);
  const [topNDraft, setTopNDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!filters) {
    return (
      <span
        data-testid="scan-list-filter-badge"
        className="rounded-full bg-muted/20 px-2 py-0.5 text-xs font-medium text-muted"
      >
        …
      </span>
    );
  }

  const ceilVal = ceilDraft === null ? filters.max_half_spread_pct : Number(ceilDraft);
  const topNVal = topNDraft === null ? filters.top_n : Number(topNDraft);
  const dirty =
    (ceilDraft !== null &&
      ceilDraft.trim() !== "" &&
      Number.isFinite(ceilVal) &&
      ceilVal !== filters.max_half_spread_pct) ||
    (topNDraft !== null &&
      topNDraft.trim() !== "" &&
      Number.isInteger(topNVal) &&
      topNVal !== filters.top_n);

  async function apply() {
    setBusy(true);
    setErr(null);
    try {
      const patch: Partial<ScanListFilters> = {};
      if (ceilDraft !== null && ceilDraft.trim() !== "")
        patch.max_half_spread_pct = Number(ceilDraft);
      if (topNDraft !== null && topNDraft.trim() !== "")
        patch.top_n = Number(topNDraft);
      const res = await setScanListFilters(patch);
      onApplied(res);
      setCeilDraft(null);
      setTopNDraft(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center gap-1.5" data-testid="scan-list-filter">
      <span
        data-testid="scan-list-filter-badge"
        title="Read-time list minimisation: half-spread ceiling + top-N by tradability"
        className="rounded-full bg-blue/20 px-2 py-0.5 text-xs font-medium text-blue"
      >
        {filters.max_half_spread_pct > 0 ? `≤${filters.max_half_spread_pct}%` : "—"}
        {" · "}
        {filters.top_n > 0 ? `top ${filters.top_n}` : "all"}
      </span>

      {busy ? (
        <span className="flex items-center gap-1.5 text-blue" data-testid="scan-list-filter-applying">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue/30 border-t-blue" />
          Applying…
        </span>
      ) : (
        <span className="flex items-center gap-1">
          <label className="flex items-center gap-0.5 text-[10px] text-muted">
            ≤
            <input
              type="number"
              min={0}
              step={0.01}
              data-testid="scan-list-ceiling-input"
              aria-label="Half-spread ceiling (percent, 0 = off)"
              value={ceilDraft ?? String(filters.max_half_spread_pct)}
              onChange={(e) => {
                setErr(null);
                setCeilDraft(e.target.value);
              }}
              className="w-14 rounded border border-border bg-bg px-1 py-0.5 text-xs text-text hover:border-blue/60"
            />
            %
          </label>
          <label className="flex items-center gap-0.5 text-[10px] text-muted">
            top
            <input
              type="number"
              min={0}
              step={1}
              data-testid="scan-list-topn-input"
              aria-label="Top-N cap by tradability (0 = off)"
              value={topNDraft ?? String(filters.top_n)}
              onChange={(e) => {
                setErr(null);
                setTopNDraft(e.target.value);
              }}
              className="w-14 rounded border border-border bg-bg px-1 py-0.5 text-xs text-text hover:border-blue/60"
            />
          </label>
          {dirty && (
            <button
              onClick={apply}
              data-testid="scan-list-filter-apply"
              title="Apply — trims the list on the next fetch; no re-scan."
              className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
            >
              Apply
            </button>
          )}
        </span>
      )}

      <InfoTip text={NOTE} />
      {err && (
        <span className="text-red" data-testid="scan-list-filter-error">
          {err}
        </span>
      )}
    </span>
  );
}
