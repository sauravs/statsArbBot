import type { Strategy } from "@/lib/api";

// Classification for the backtest strategy list + detail panel (docs/QA.md,
// 2026-07-22 "Why does the dashboard show so many PROFITABLE strategies…").
//
// The leaderboard used to rank 69 runs by net P&L with nothing to separate them.
// Of the visible top 15, 11 were in-sample and 4 were zero-cost counterfactuals —
// zero were realistic out-of-sample results, yet all 15 rendered identically. This
// module supplies the two things that were missing:
//
//   SAFETY  — is this number tradeable, and was it earned on data the config had
//             never seen? Derived ONLY from config (costs, span), never from names.
//             Names are operator-typed and can lie; `taker_fee_pct = 0` cannot.
//   TAXONOMY — which experiment family this run belongs to. Derived from the name
//             prefix, because that is genuinely the only record of intent, and a
//             wrong guess here is cosmetic rather than misleading.
//
// Everything is a pure function of one Strategy row, so both panels classify
// identically and the whole thing is unit-testable without React or a network.

/** Costs the campaign modelled as "realistic": 0.05% fee + 0.05% slippage per side.
 *  Anything below this is a diagnostic — it buys fills nobody can actually buy.
 *  (Per docs/strategy.md 2026-07-22, real taker is 0.045 + 0.0316 = 0.0766% total,
 *  so a run AT this level is mildly pessimistic, never optimistic. That asymmetry
 *  is why only "below" is flagged.) */
export const MODELLED_FEE_PCT = 0.05;
export const MODELLED_SLIPPAGE_PCT = 0.05;

/** The designated in-sample window — the one span the parameter sweeps were tuned
 *  on, and the reason their headline numbers look so good. */
export const IN_SAMPLE_START = Date.UTC(2026, 2, 1); // 2026-03-01
export const IN_SAMPLE_END = Date.UTC(2026, 5, 23); // 2026-06-23

/** Named re-validation spans (docs/strategy.md). s1 is the in-sample window; s2–s4
 *  step backwards through history and are the honest test. */
export const SPANS = [
  { name: "s1", start: Date.UTC(2026, 2, 1), end: Date.UTC(2026, 5, 23) },
  { name: "s2", start: Date.UTC(2025, 10, 7), end: Date.UTC(2026, 2, 1) },
  { name: "s3", start: Date.UTC(2025, 6, 16), end: Date.UTC(2025, 10, 7) },
  { name: "s4", start: Date.UTC(2025, 2, 24), end: Date.UTC(2025, 6, 16) },
] as const;

/** A span counts as in-sample once this much of it sits inside s1. Below this it is
 *  "overlaps" — partially-seen data, which is neither a clean tune nor a clean test. */
const IN_SAMPLE_OVERLAP_THRESHOLD = 0.9;

/** The rank-#1 baseline config. Deliberately a CONFIG fingerprint, not a name: the
 *  same parameters were saved under three different names ("Untitled strategy",
 *  "entry-sweep-3.0", "sweep-exit-0.5"), all landing on the identical $1,865 — while
 *  24 unrelated ad-hoc runs also carry the name "Untitled strategy". Matching on the
 *  name would file a third of the list under "Baseline". */
export const BASELINE_REFERENCE = {
  entry_threshold: 3.0,
  exit_threshold: 0.5,
  stop_threshold: 4.0,
  pvalue_max: 0.01,
  max_half_life_h: 72,
  scan_window_days: 21,
  trade_window_days: 7,
  zscore_window: 21,
  taker_fee_pct: MODELLED_FEE_PCT,
  slippage_pct: MODELLED_SLIPPAGE_PCT,
} as const;

export type CostLabel = "ZERO_COST" | "REDUCED_COST" | "MODELLED_COST";
export type SpanLabel =
  | "IN_SAMPLE"
  | "OVERLAPS_IN_SAMPLE"
  | "OUT_OF_SAMPLE"
  | "NO_SPAN";

export type FamilyKey =
  | "baseline"
  | "entry-sweep"
  | "exit-sweep"
  | "pvalue-sweep"
  | "revalidation"
  | "half-life"
  | "z-stop"
  | "cost-decomposition"
  | "window-sweep"
  | "seed-defaults"
  | "ad-hoc";

export interface SafetyFlags {
  cost: CostLabel;
  span: SpanLabel;
  /** Costs are at least the modelled level — this run could exist in reality. */
  tradeable: boolean;
  /** Tradeable AND measured on data the config had never seen. The only kind of
   *  row whose net P&L is evidence about future money. */
  realistic: boolean;
}

export interface Classification {
  family: FamilyKey;
  familyLabel: string;
  safety: SafetyFlags;
  /** "s1".."s4" when the span matches a named re-validation window, else null. */
  spanName: string | null;
  /** Human span, e.g. "2026-03-01 → 2026-06-23 (114d)". */
  spanText: string;
  /** Config-diff summary against BASELINE_REFERENCE — generated for every run so
   *  no backfill of the DB `description` column is required. */
  autoDescription: string;
  /** What to actually show: the operator's own text wins, then the curated family
   *  blurb, then the generated diff. */
  description: string;
}

export interface FamilyDescription {
  label: string;
  /** What this family of runs is testing. */
  what: string;
  /** What the campaign concluded — the payoff line. */
  finding: string;
  /** Plain-language image, in the register of docs/QA.md. Optional. */
  analogy?: string;
}

/** Curated text for the families the campaign actually produced. Families without
 *  an entry fall back to the generated config diff. */
export const FAMILY_DESCRIPTIONS: Record<FamilyKey, FamilyDescription> = {
  baseline: {
    label: "Baseline",
    what: "The reference configuration every sweep is measured against: entry |Z| 3.0, exit |Z| 0.5, stop |Z| 4.0, p-value 0.01, half-life cap 72h, 21-day scan into a 7-day trade window.",
    finding:
      "Tops the leaderboard at roughly +$1,865 — but only on the in-sample window it shares with every sweep. The same parameters were saved three times under different names and produced the identical number.",
    analogy:
      "Par for the course. Useful as a yardstick, and it tells you nothing about how anyone plays a course they have never seen.",
  },
  "entry-sweep": {
    label: "Entry |Z| sweep",
    what: "Varies how far the spread must diverge before a pair is opened, holding everything else fixed.",
    finding:
      "The dominant lever. Peaks at 3.5 in-sample and anything at or below 2.5 is ruinous — but the ranking is largely a friction artifact: each trade pays a flat ~$0.40 toll, so a high bar simply refuses the trades the toll would eat. At zero cost the ordering inverts and entry 3.0 wins. Out-of-sample, every value is negative.",
    analogy:
      "A toll road. Raising the entry bar is refusing short trips because the toll eats them — sensible while the toll is high, and it forgoes plenty of profitable journeys.",
  },
  "exit-sweep": {
    label: "Exit |Z| sweep",
    what: "Varies the take-profit level — how far the spread must revert before the position is closed.",
    finding:
      "Noise. The whole sweep spans a few hundred dollars with no coherent trend, which is the signature of a parameter that is not doing any work. Keep 0.5.",
    analogy:
      "Rearranging the deckchairs. Every arrangement measures slightly differently and none of it changes where the ship is going.",
  },
  "pvalue-sweep": {
    label: "p-value sweep",
    what: "Varies the cointegration gate — how statistically convincing a pair's relationship must be before it is allowed into the universe.",
    finding:
      "Potent below 0.05 and saturated above it: 0.05, 0.10 and 0.15 all return the identical −$1,176 because the gate has stopped excluding anything. Keep it tight at 0.01. It prevents ruin rather than creating profit.",
    analogy:
      "A bouncer with a guest list. Tighten it and the room stays good; loosen it past a point and you are simply letting everyone in, so loosening further changes nothing.",
  },
  revalidation: {
    label: "Multi-span re-validation",
    what: "Takes a config tuned on the in-sample window and replays it, unchanged, across three earlier spans it has never seen. This is the honest test.",
    finding:
      "Where the strategy falls apart. Entry 3.5 is curve-fit: +$2,307 in-sample collapses to −$536 across the out-of-sample spans. Entry 3.0 is far worse at −$5,445.",
    analogy:
      "Auditioning with the one song you have practised for months. You will sound brilliant, and it says nothing about your sight-reading — these spans are the sight-reading test.",
  },
  "half-life": {
    label: "Half-life sweep",
    what: "Varies the cap on how slowly a pair is allowed to revert before it is refused entry.",
    finding:
      "Non-binding — the knob is inert. Tightening 72h to 24h removes only about 4% of trades and leaves drawdown flat, because the admitted pairs already revert quickly. The out-of-sample losses are not slow reverters; they are pairs whose relationship simply breaks.",
    analogy:
      "A thermostat in a house with no heater. You can turn the dial all you like.",
  },
  "z-stop": {
    label: "Z-stop sweep",
    what: "Varies the hard stop — how far a losing spread may diverge before the position is cut.",
    finding:
      "A pure risk/return trade-off, not an improvement. Wider gives better net and worse drawdown, in lockstep; no setting improves both. A tight stop is actively worse, because trades that dip to 3.75 mostly come back — the leash books would-be winners as losses.",
    analogy:
      "A see-saw. You can tilt it either way; you never lift it.",
  },
  "cost-decomposition": {
    label: "Cost decomposition",
    what: "Re-runs a config with fees and slippage reduced or removed entirely, to separate the raw signal from the friction of trading it. These are measurements, not strategies.",
    finding:
      "The result that reversed the campaign's conclusion: the signal is real (+$2,554 gross out-of-sample, 66–69% win rates, drawdowns of 5.6–14.5%) and friction alone destroys it, at a flat ~$0.40 per trade. Every run in this family is untradeable by construction — you cannot trade for free.",
    analogy:
      "A car's top speed measured in a vacuum. A real and useful physics number, and not how fast you will get to work.",
  },
  "window-sweep": {
    label: "Scan / trade window sweep",
    what: "Varies the walk-forward geometry — how many days of history each window scans to pick pairs, and how long it then trades them.",
    finding:
      "Exploratory. These runs vary the window lengths alongside other parameters, so they are not a clean single-variable sweep; read them as scouting rather than evidence.",
  },
  "seed-defaults": {
    label: "Seed defaults",
    what: "The S1–S4 starter strategies created by the Seed button, as a first look at the entry-threshold range.",
    finding:
      "Demonstration presets rather than campaign results — several were never run to completion.",
  },
  "ad-hoc": {
    label: "Ad-hoc exploration",
    what: "Individually created runs from manual experimentation — many still carrying the default name. They vary several parameters at once and span arbitrary date ranges.",
    finding:
      "No controlled comparison behind them: with more than one variable moving and no shared span, a good number here cannot be attributed to any particular choice.",
    analogy:
      "Lab notebook scribbles. Worth keeping, and not the same thing as an experiment.",
  },
};

/** Name-prefix → family. Order matters: the first match wins, so longer / more
 *  specific prefixes are listed before the ones they extend. */
const FAMILY_PATTERNS: { test: RegExp; family: FamilyKey }[] = [
  { test: /^cost-?\d/i, family: "cost-decomposition" }, // cost-000-*, cost-002-*, cost000-e30-*
  { test: /^entry-sweep/i, family: "entry-sweep" },
  { test: /^sweep\d*-exit/i, family: "exit-sweep" }, // sweep-exit-*, sweep2-exit-*
  { test: /^pval-sweep/i, family: "pvalue-sweep" },
  { test: /^reval-/i, family: "revalidation" },
  { test: /^hl-/i, family: "half-life" },
  { test: /^stop-/i, family: "z-stop" },
  { test: /^scan\s*\d+\s*,\s*trade\s*\d+/i, family: "window-sweep" },
  { test: /^S[1-4]\s*—/i, family: "seed-defaults" },
];

const DAY_MS = 86_400_000;

function parseDate(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** Fraction of [start, end] that falls inside the in-sample window. 0 when disjoint. */
function inSampleOverlapFraction(start: number, end: number): number {
  const span = end - start;
  if (span <= 0) return start >= IN_SAMPLE_START && start <= IN_SAMPLE_END ? 1 : 0;
  const lo = Math.max(start, IN_SAMPLE_START);
  const hi = Math.min(end, IN_SAMPLE_END);
  return hi <= lo ? 0 : (hi - lo) / span;
}

export function classifySpan(s: Strategy): { label: SpanLabel; spanName: string | null } {
  const start = parseDate(s.start_time);
  const end = parseDate(s.end_time);
  if (start == null || end == null) return { label: "NO_SPAN", spanName: null };

  // Snap to a named re-validation span when both ends land within a day of it, so
  // s2/s3/s4 are recognised despite timestamp jitter on the boundaries.
  const named =
    SPANS.find(
      (w) => Math.abs(start - w.start) <= DAY_MS && Math.abs(end - w.end) <= DAY_MS,
    ) ?? null;

  const overlap = inSampleOverlapFraction(start, end);
  const label: SpanLabel =
    overlap >= IN_SAMPLE_OVERLAP_THRESHOLD
      ? "IN_SAMPLE"
      : overlap > 0
        ? "OVERLAPS_IN_SAMPLE"
        : "OUT_OF_SAMPLE";

  return { label, spanName: named?.name ?? null };
}

export function classifyCost(s: Strategy): CostLabel {
  const fee = s.taker_fee_pct ?? 0;
  const slip = s.slippage_pct ?? 0;
  if (fee === 0 && slip === 0) return "ZERO_COST";
  if (fee < MODELLED_FEE_PCT || slip < MODELLED_SLIPPAGE_PCT) return "REDUCED_COST";
  return "MODELLED_COST";
}

/** True when the run's parameters match the rank-#1 baseline on every axis that the
 *  sweeps varied, AND it ran on the in-sample window. */
function isBaselineConfig(s: Strategy, span: SpanLabel): boolean {
  if (span !== "IN_SAMPLE") return false;
  return (
    s.entry_threshold === BASELINE_REFERENCE.entry_threshold &&
    s.exit_threshold === BASELINE_REFERENCE.exit_threshold &&
    s.stop_threshold === BASELINE_REFERENCE.stop_threshold &&
    s.pvalue_max === BASELINE_REFERENCE.pvalue_max &&
    s.max_half_life_h === BASELINE_REFERENCE.max_half_life_h &&
    s.scan_window_days === BASELINE_REFERENCE.scan_window_days &&
    s.trade_window_days === BASELINE_REFERENCE.trade_window_days &&
    s.zscore_window === BASELINE_REFERENCE.zscore_window &&
    s.taker_fee_pct === BASELINE_REFERENCE.taker_fee_pct &&
    s.slippage_pct === BASELINE_REFERENCE.slippage_pct
  );
}

export function classifyFamily(s: Strategy, span: SpanLabel): FamilyKey {
  const name = (s.name ?? "").trim();
  for (const { test, family } of FAMILY_PATTERNS) {
    if (test.test(name)) {
      // A cost run at full cost is the control arm of the decomposition; a sweep
      // member with zeroed costs is a diagnostic. Both keep their family — the cost
      // badge carries the tradeability warning independently, so the taxonomy never
      // has to double as a safety signal.
      return family;
    }
  }
  // Config fingerprint, checked only after the explicit prefixes so a deliberately
  // named sweep member keeps its own family even when its parameters coincide with
  // the baseline (entry-sweep-3.0 and sweep-exit-0.5 both do).
  if (isBaselineConfig(s, span)) return "baseline";
  return "ad-hoc";
}

function fmtDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function spanText(s: Strategy): string {
  const start = parseDate(s.start_time);
  const end = parseDate(s.end_time);
  if (start == null || end == null) return "No span set — runs over all available history";
  const days = Math.max(0, Math.round((end - start) / DAY_MS));
  return `${fmtDate(start)} → ${fmtDate(end)} (${days}d)`;
}

/** Number formatted without trailing zeros — 3.50 → "3.5", 72.0 → "72". */
function num(n: number): string {
  return String(Number(n.toFixed(4)));
}

/** A config diff against the baseline reference, in plain sentences. Generated for
 *  every run so each row can explain itself with no DB backfill. */
export function autoDescription(s: Strategy, span: SpanLabel): string {
  const diffs: string[] = [];
  const cmp = (
    actual: number | null | undefined,
    ref: number,
    label: string,
    unit = "",
  ) => {
    if (actual == null || actual === ref) return;
    diffs.push(`${label} ${num(actual)}${unit} (baseline ${num(ref)}${unit})`);
  };

  cmp(s.entry_threshold, BASELINE_REFERENCE.entry_threshold, "entry |Z|");
  cmp(s.exit_threshold, BASELINE_REFERENCE.exit_threshold, "exit |Z|");
  cmp(s.stop_threshold, BASELINE_REFERENCE.stop_threshold, "stop |Z|");
  cmp(s.pvalue_max, BASELINE_REFERENCE.pvalue_max, "p-value gate");
  cmp(s.max_half_life_h, BASELINE_REFERENCE.max_half_life_h, "half-life cap", "h");
  cmp(s.scan_window_days, BASELINE_REFERENCE.scan_window_days, "scan window", "d");
  cmp(s.trade_window_days, BASELINE_REFERENCE.trade_window_days, "trade window", "d");
  cmp(s.zscore_window, BASELINE_REFERENCE.zscore_window, "Z-window");

  // Costs read better as one clause than as two independent diffs, because it is
  // the pair of them that decides tradeability.
  const cost = classifyCost(s);
  if (cost === "ZERO_COST") {
    diffs.push(
      `fees and slippage set to 0 (baseline ${num(MODELLED_FEE_PCT)}% + ${num(MODELLED_SLIPPAGE_PCT)}%)`,
    );
  } else if (cost === "REDUCED_COST") {
    diffs.push(
      `costs reduced to ${num(s.taker_fee_pct)}% fee + ${num(s.slippage_pct)}% slippage (baseline ${num(MODELLED_FEE_PCT)}% + ${num(MODELLED_SLIPPAGE_PCT)}%)`,
    );
  }

  const parts: string[] = [];
  parts.push(
    diffs.length === 0
      ? "Baseline parameters, unchanged."
      : `Changes from baseline: ${diffs.join("; ")}.`,
  );

  const spanSuffix =
    span === "IN_SAMPLE"
      ? " — the in-sample window every sweep was tuned on."
      : span === "OVERLAPS_IN_SAMPLE"
        ? " — overlaps the in-sample window, so this is not a clean test."
        : span === "OUT_OF_SAMPLE"
          ? " — data this config had never seen."
          : "";
  parts.push(`Span: ${spanText(s)}${spanSuffix}`);

  return parts.join(" ");
}

export function classify(s: Strategy): Classification {
  const { label: span, spanName } = classifySpan(s);
  const cost = classifyCost(s);
  const family = classifyFamily(s, span);
  const tradeable = cost === "MODELLED_COST";
  const auto = autoDescription(s, span);

  return {
    family,
    familyLabel: FAMILY_DESCRIPTIONS[family].label,
    safety: {
      cost,
      span,
      tradeable,
      realistic: tradeable && span === "OUT_OF_SAMPLE",
    },
    spanName,
    spanText: spanText(s),
    autoDescription: auto,
    // The operator's own text wins when set; the curated family blurb is next,
    // because it explains intent that no config diff can recover; the diff is the
    // guaranteed fallback.
    description: s.description?.trim() || FAMILY_DESCRIPTIONS[family].what || auto,
  };
}

// ── group statistics ────────────────────────────────────────────────────────────

export interface FamilyGroup {
  family: FamilyKey;
  label: string;
  strategies: Strategy[];
  /** Rows counted in the stats — those that actually produced a net P&L. */
  scored: number;
  medianNet: number | null;
  bestNet: number | null;
  worstNet: number | null;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Display order: the honest families first, the seductive ones last. Deliberately
 *  NOT ranked by P&L — a leaderboard is the thing this UI exists to defuse. */
const FAMILY_ORDER: FamilyKey[] = [
  "revalidation",
  "baseline",
  "entry-sweep",
  "exit-sweep",
  "pvalue-sweep",
  "half-life",
  "z-stop",
  "window-sweep",
  "cost-decomposition",
  "seed-defaults",
  "ad-hoc",
];

export type SortKey = "default" | "pnl" | "newest" | "name";

/** Sort rows. "default" is name-ascending with numeric awareness, so a sweep reads
 *  in parameter order (entry-sweep-3.5 before 3.75 before 4.0) — the order that
 *  shows the curve rather than the podium. */
export function sortStrategies(rows: Strategy[], sort: SortKey): Strategy[] {
  const out = [...rows];
  switch (sort) {
    case "pnl":
      // Nulls last — a strategy that never ran is not a $0 result.
      return out.sort((a, b) => (b.net_pnl ?? -Infinity) - (a.net_pnl ?? -Infinity));
    case "newest":
      return out.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    case "default":
    case "name":
      return out.sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }),
      );
  }
}

/** Sort the GROUPS themselves. Without this, choosing a sort in the default grouped
 *  view changes nothing an operator can see: rows move inside their group, but the
 *  groups stay in a fixed order and the headers show the same medians — and if the
 *  groups happen to be collapsed, literally nothing on screen moves. An explicit
 *  sort request has to reorder what is actually visible.
 *
 *  Under "pnl" this ranks by MEDIAN, matching what the header displays and keeping
 *  the median-not-best principle intact even when the operator asks for a ranking. */
export function sortGroups(groups: FamilyGroup[], sort: SortKey): FamilyGroup[] {
  const out = [...groups];
  switch (sort) {
    case "pnl":
      // Groups with nothing scored yet sink to the bottom rather than pretending
      // to be worth $0.
      return out.sort((a, b) => (b.medianNet ?? -Infinity) - (a.medianNet ?? -Infinity));
    case "newest":
      return out.sort((a, b) => newestCreatedAt(b).localeCompare(newestCreatedAt(a)));
    case "name":
      return out.sort((a, b) => a.label.localeCompare(b.label));
    case "default":
      // The deliberate order set by FAMILY_ORDER — honest families first.
      return out;
  }
}

function newestCreatedAt(g: FamilyGroup): string {
  return g.strategies.reduce((max, s) => (s.created_at ?? "") > max ? (s.created_at ?? "") : max, "");
}

export function groupByFamily(strategies: Strategy[]): FamilyGroup[] {
  const buckets = new Map<FamilyKey, Strategy[]>();
  for (const s of strategies) {
    const { family } = classify(s);
    const bucket = buckets.get(family);
    if (bucket) bucket.push(s);
    else buckets.set(family, [s]);
  }

  return FAMILY_ORDER.filter((f) => buckets.has(f)).map((family) => {
    const rows = buckets.get(family)!;
    // Never-run rows stay in the count but out of the statistics — a pending
    // strategy is not a $0 result.
    const nets = rows.map((r) => r.net_pnl).filter((n): n is number => n != null);
    return {
      family,
      label: FAMILY_DESCRIPTIONS[family].label,
      strategies: rows,
      scored: nets.length,
      medianNet: median(nets),
      bestNet: nets.length ? Math.max(...nets) : null,
      worstNet: nets.length ? Math.min(...nets) : null,
    };
  });
}
