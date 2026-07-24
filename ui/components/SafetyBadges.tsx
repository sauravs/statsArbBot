"use client";

import {
  DSR_SIGNIFICANT,
  dsrLevel,
  type Classification,
  type CostLabel,
  type SpanLabel,
} from "@/lib/strategyTaxonomy";

// Two deliberately distinct tiers of badge (docs/QA.md 2026-07-22):
//
//   SAFETY   — loud. Whether this run's number is tradeable at all, and whether it
//              was earned on data the config had never seen. These are the two
//              qualifiers that were missing when a zero-cost counterfactual sat next
//              to a real run "looking like its peer, economically incomparable".
//   TAXONOMY — quiet. Which experiment family the run belongs to. Useful context,
//              never a warning, so it is styled to recede.
//
// Shared by the list and the detail panel so a counterfactual is unmistakable
// wherever the operator happens to be looking.

const COST_BADGE: Record<CostLabel, { full: string; short: string; tip: string } | null> = {
  ZERO_COST: {
    full: "⚠ NO-COST DIAGNOSTIC — not tradeable",
    short: "⚠ NO-COST",
    tip: "Fees and slippage were set to zero. This isolates the raw signal by removing friction — a real measurement, but not a strategy you could run, because you cannot trade for free. Like a car's top speed measured in a vacuum.",
  },
  REDUCED_COST: {
    full: "⚠ REDUCED-COST DIAGNOSTIC — not tradeable",
    short: "⚠ LOW-COST",
    tip: "Fees and/or slippage were set below the modelled 0.05% + 0.05% per side. Useful for measuring how sensitive the result is to friction, but it assumes execution cheaper than the operator can actually get.",
  },
  MODELLED_COST: null,
};

const SPAN_BADGE: Record<SpanLabel, { full: string; short: string; tip: string; tone: string }> = {
  IN_SAMPLE: {
    full: "IN-SAMPLE",
    short: "IN-SAMPLE",
    tone: "border-yellow/50 bg-yellow/15 text-yellow",
    tip: "Measured on the 2026-03-01 → 06-23 window that every parameter sweep was tuned on. The strategy has effectively already seen this data, so a good number here is expected and proves nothing. Like auditioning with the one song you have practised for months.",
  },
  OVERLAPS_IN_SAMPLE: {
    full: "OVERLAPS IN-SAMPLE",
    // Span labels are short enough to stay spelled out even in the list — an
    // abbreviation here ("OVERLAPS IS") reads as noise, and this badge is a warning.
    short: "OVERLAPS IN-SAMPLE",
    tone: "border-yellow/50 bg-yellow/15 text-yellow",
    tip: "This span partly covers the 2026-03-01 → 06-23 tuning window, so the result mixes data the config has seen with data it has not. Neither a clean tune nor a clean test — treat it as scouting, not evidence.",
  },
  OUT_OF_SAMPLE: {
    full: "OUT-OF-SAMPLE",
    short: "OUT-OF-SAMPLE",
    tone: "border-green/50 bg-green/15 text-green",
    tip: "Measured on data outside the tuning window — the config had never seen it. This is the honest test, and the only kind of span whose P&L says anything about future money.",
  },
  NO_SPAN: {
    full: "NO SPAN SET",
    short: "NO SPAN",
    tone: "border-border bg-muted/10 text-muted",
    tip: "No explicit date range was set, so the run used whatever history was available. Without a fixed span it cannot be compared like-for-like against the sweeps.",
  },
};

/** The loud tier: cost first (it decides tradeability), then span. */
export function SafetyBadges({
  classification,
  compact = false,
}: {
  classification: Classification;
  compact?: boolean;
}) {
  const cost = COST_BADGE[classification.safety.cost];
  const span = SPAN_BADGE[classification.safety.span];
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="safety-badges">
      {cost && (
        <span
          title={cost.tip}
          data-testid="badge-cost"
          className="cursor-help rounded border border-red/60 bg-red/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red"
        >
          {compact ? cost.short : cost.full}
        </span>
      )}
      <span
        title={span.tip}
        data-testid="badge-span"
        className={`cursor-help rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${span.tone}`}
      >
        {compact ? span.short : span.full}
        {classification.spanName && ` ${classification.spanName}`}
      </span>
    </span>
  );
}

/** Deflated-Sharpe "corrected significance" badge (Phase-2 Slice 4, gate B3). The
 *  leaderboard shows the best of a long search; DSR asks whether that best survives
 *  correction for how many configs were tried. Rendered only when the run has a DSR
 *  (enough windows to score, and /significance has resolved). */
export function DsrBadge({ dsr }: { dsr: number | null | undefined }) {
  const level = dsrLevel(dsr);
  if (level === "unknown") return null;
  const significant = level === "significant";
  const value = (dsr as number).toFixed(2);
  return (
    <span
      title={
        significant
          ? `Deflated Sharpe Ratio ${value} ≥ ${DSR_SIGNIFICANT}: this result survives correction for the number of configs searched — significant at 5%. The rare row whose edge is not just the luckiest draw of the sweep.`
          : `Deflated Sharpe Ratio ${value} < ${DSR_SIGNIFICANT}: after correcting for how many configs were tried, this result is indistinguishable from the luckiest draw of the search. Not significant.`
      }
      data-testid="badge-dsr"
      className={`cursor-help rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        significant
          ? "border-green/50 bg-green/15 text-green"
          : "border-border bg-muted/10 text-muted"
      }`}
    >
      {significant ? `DSR ${value} ✓` : `DSR ${value}`}
    </span>
  );
}

/** The quiet tier: which experiment this run belongs to. Styled to recede — it is
 *  context, not a warning, and must never compete with the safety badges. */
export function FamilyBadge({
  classification,
  tip,
}: {
  classification: Classification;
  tip?: string;
}) {
  return (
    <span
      title={tip}
      data-testid="badge-family"
      className={`rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted ${
        tip ? "cursor-help" : ""
      }`}
    >
      {classification.familyLabel}
    </span>
  );
}

/** Row styling for untradeable runs: muted and striped, so a counterfactual reads
 *  as "excluded from the real comparison" at a glance without being hidden. */
export const COUNTERFACTUAL_ROW_STYLE: React.CSSProperties = {
  backgroundImage:
    "repeating-linear-gradient(135deg, rgba(255,71,87,0.07) 0 6px, transparent 6px 12px)",
};
