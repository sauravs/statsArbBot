"use client";

import { useMemo, useState } from "react";
import { type BacktestStatus, type Strategy } from "@/lib/api";
import {
  FAMILY_DESCRIPTIONS,
  classify,
  groupByFamily,
  phaseMatches,
  sortGroups,
  sortStrategies,
  type Classification,
  type FamilyKey,
  type PhaseFilter,
  type SortKey,
} from "@/lib/strategyTaxonomy";
import {
  COUNTERFACTUAL_ROW_STYLE,
  DsrBadge,
  FamilyBadge,
  PhaseBadge,
  SafetyBadges,
} from "./SafetyBadges";
import InfoTip from "./InfoTip";

// Strategy comparison for the walk-forward backtest (PRD F8.4), rebuilt around the
// finding in docs/QA.md (2026-07-22): ranked best-first with no other signal, this
// list was "the most persuasive screen in the app and also the most misleading" —
// of the visible top 15, eleven were in-sample and four were zero-cost
// counterfactuals, and all fifteen rendered identically.
//
// So the default view is no longer a leaderboard. Runs are grouped into the
// experiment families they came from, each header carrying a MEDIAN and a range
// rather than a best (a "best" would quietly rebuild the podium we are dismantling),
// and every row states whether its number is tradeable and whether it was earned on
// unseen data. Counterfactuals stay visible — hiding them would trade one distortion
// for another — but they are struck through with stripes and a loud badge.

type SpanFilter = "all" | "oos" | "in-sample";
type CostFilter = "all" | "tradeable" | "diagnostic";

const SORT_LABELS: Record<SortKey, string> = {
  default: "Default",
  pnl: "Net P&L",
  newest: "Newest",
  name: "Name",
};

export default function StrategyList({
  strategies,
  selectedId,
  onSelect,
  onSeed,
  seeding,
}: {
  strategies: Strategy[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onSeed: () => void;
  seeding: boolean;
}) {
  const [grouped, setGrouped] = useState(true);
  const [sort, setSort] = useState<SortKey>("default");
  const [realisticOnly, setRealisticOnly] = useState(false);
  const [family, setFamily] = useState<FamilyKey | "all">("all");
  const [spanFilter, setSpanFilter] = useState<SpanFilter>("all");
  const [costFilter, setCostFilter] = useState<CostFilter>("all");
  const [collapsed, setCollapsed] = useState<Set<FamilyKey>>(new Set());
  // Phase filter (Slice 6). DEFAULT "all" — Phase 1 is never hidden; the badge +
  // toggle do the disambiguation (operator decision 2026-07-24).
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");

  // Classify once per render pass; both the filters and every row need it.
  const classified = useMemo(
    () => strategies.map((s) => ({ s, c: classify(s) })),
    [strategies],
  );

  const familiesPresent = useMemo(() => {
    const seen = new Set<FamilyKey>();
    for (const { c } of classified) seen.add(c.family);
    return seen;
  }, [classified]);

  const visible = useMemo(() => {
    return classified
      .filter(({ s, c }) => {
        if (!phaseMatches(s, phaseFilter)) return false;
        if (realisticOnly && !c.safety.realistic) return false;
        if (family !== "all" && c.family !== family) return false;
        if (spanFilter === "oos" && c.safety.span !== "OUT_OF_SAMPLE") return false;
        if (
          spanFilter === "in-sample" &&
          c.safety.span !== "IN_SAMPLE" &&
          c.safety.span !== "OVERLAPS_IN_SAMPLE"
        )
          return false;
        if (costFilter === "tradeable" && !c.safety.tradeable) return false;
        if (costFilter === "diagnostic" && c.safety.tradeable) return false;
        return true;
      })
      .map(({ s }) => s);
  }, [classified, realisticOnly, family, spanFilter, costFilter, phaseFilter]);

  const sorted = useMemo(() => sortStrategies(visible, sort), [visible, sort]);
  // Sort the groups too, not just the rows inside them — otherwise picking a sort
  // in the default grouped view moves nothing the operator can see.
  const groups = useMemo(
    () => (grouped ? sortGroups(groupByFamily(sorted), sort) : []),
    [grouped, sorted, sort],
  );
  const allCollapsed = groups.length > 0 && groups.every((g) => collapsed.has(g.family));

  const filtersActive =
    realisticOnly ||
    family !== "all" ||
    spanFilter !== "all" ||
    costFilter !== "all" ||
    phaseFilter !== "all";

  function toggleGroup(key: FamilyKey) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wider text-muted">
          Strategies
          <span
            className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue"
            data-testid="strategy-count"
          >
            {filtersActive ? `${visible.length}/${strategies.length}` : strategies.length}
          </span>
        </h2>
        <button
          onClick={onSeed}
          disabled={seeding}
          className="rounded-lg border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-blue/60 hover:text-text disabled:opacity-40"
          data-testid="seed-defaults-btn"
        >
          {seeding ? "Seeding…" : "Seed S1–S4"}
        </button>
      </div>

      {strategies.length > 0 && (
        <div className="mb-4 space-y-2 rounded-lg border border-border bg-bg/60 p-3">
          {/* The one switch that answers "which of these numbers is actually
              evidence?" — kept off by default so nothing is hidden until asked. */}
          <label
            className="flex cursor-pointer items-center gap-2 text-xs text-text"
            data-testid="realistic-only-toggle"
          >
            <input
              type="checkbox"
              checked={realisticOnly}
              onChange={(e) => setRealisticOnly(e.target.checked)}
              className="accent-blue"
            />
            <span>
              Realistic runs only
              <InfoTip text="Show only runs with tradeable costs AND a span the config had never seen — the only rows whose net P&L is evidence about future money. Everything else is either untradeable (costs zeroed) or was measured on the window the parameters were tuned on." />
            </span>
            {/* Collapsing every group leaves a screen with no rows on it and no
                obvious way back short of clicking each header. */}
            {grouped && groups.length > 0 && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setCollapsed(allCollapsed ? new Set() : new Set(groups.map((g) => g.family)));
                }}
                className="ml-auto rounded border border-border px-1.5 py-0.5 text-[10px] text-muted transition-colors hover:border-blue/60 hover:text-text"
                data-testid="expand-all-btn"
              >
                {allCollapsed ? "Expand all" : "Collapse all"}
              </button>
            )}
          </label>

          <div className="grid grid-cols-2 gap-2">
            <Control label="Group">
              <select
                value={grouped ? "family" : "none"}
                onChange={(e) => setGrouped(e.target.value === "family")}
                className={selectClass}
                data-testid="group-mode-select"
              >
                <option value="family">Experiment family</option>
                <option value="none">None (flat)</option>
              </select>
            </Control>
            <Control
              label="Sort"
              tip="Ranking by Net P&L puts a winners' podium back on screen — every loss is still in the list, just scrolled below the fold. Available, but not the default."
            >
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value as SortKey);
                  // A sort you cannot see is useless: if the groups happen to be
                  // collapsed, reordering them silently is indistinguishable from
                  // the control being broken. Asking for an order re-opens the rows.
                  setCollapsed(new Set());
                }}
                className={selectClass}
                data-testid="sort-select"
              >
                {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                  <option key={k} value={k}>
                    {SORT_LABELS[k]}
                  </option>
                ))}
              </select>
            </Control>
            <Control label="Family">
              <select
                value={family}
                onChange={(e) => setFamily(e.target.value as FamilyKey | "all")}
                className={selectClass}
                data-testid="family-filter-select"
              >
                <option value="all">All families</option>
                {(Object.keys(FAMILY_DESCRIPTIONS) as FamilyKey[])
                  .filter((k) => familiesPresent.has(k))
                  .map((k) => (
                    <option key={k} value={k}>
                      {FAMILY_DESCRIPTIONS[k].label}
                    </option>
                  ))}
              </select>
            </Control>
            <Control label="Span">
              <select
                value={spanFilter}
                onChange={(e) => setSpanFilter(e.target.value as SpanFilter)}
                className={selectClass}
                data-testid="span-filter-select"
              >
                <option value="all">All spans</option>
                <option value="oos">Out-of-sample</option>
                <option value="in-sample">In-sample / overlapping</option>
              </select>
            </Control>
            <Control label="Costs">
              <select
                value={costFilter}
                onChange={(e) => setCostFilter(e.target.value as CostFilter)}
                className={selectClass}
                data-testid="cost-filter-select"
              >
                <option value="all">All costs</option>
                <option value="tradeable">Tradeable only</option>
                <option value="diagnostic">Diagnostics only</option>
              </select>
            </Control>
            <Control label="Phase">
              <select
                value={phaseFilter}
                onChange={(e) => setPhaseFilter(e.target.value as PhaseFilter)}
                className={selectClass}
                data-testid="phase-filter-select"
              >
                <option value="all">All phases</option>
                <option value="phase1">Phase 1</option>
                <option value="phase2">Phase 2</option>
              </select>
            </Control>
          </div>
        </div>
      )}

      {strategies.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted" data-testid="strategy-list-empty">
          No strategies yet. Create one or seed the S1–S4 baselines.
        </p>
      ) : visible.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted" data-testid="strategy-list-filtered-empty">
          No strategy matches these filters.
          {realisticOnly && (
            <>
              {" "}
              With realistic costs on unseen data, there may simply be nothing here — which
              is itself the result.
            </>
          )}
        </p>
      ) : (
        <div className="space-y-3" data-testid="strategy-list">
          {grouped
            ? groups.map((g) => {
                const isCollapsed = collapsed.has(g.family);
                const desc = FAMILY_DESCRIPTIONS[g.family];
                return (
                  <div key={g.family} data-testid="strategy-group">
                    <button
                      onClick={() => toggleGroup(g.family)}
                      aria-expanded={!isCollapsed}
                      title={`${desc.what}\n\n${desc.finding}${desc.analogy ? `\n\n${desc.analogy}` : ""}`}
                      className="flex w-full items-start gap-2 rounded-lg px-1.5 py-1.5 text-left transition-colors hover:bg-bg/60"
                      data-testid="strategy-group-header"
                    >
                      <span className="mt-0.5 select-none text-[10px] text-muted">
                        {isCollapsed ? "▶" : "▼"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-xs font-semibold text-text">
                            {g.label}
                          </span>
                          <span className="shrink-0 rounded-full bg-border/60 px-1.5 text-[10px] tabular-nums text-muted">
                            {g.strategies.length}
                          </span>
                        </span>
                        {/* Median, not best: a "best" column would quietly rebuild the
                            leaderboard this view exists to defuse. The range is what
                            shows an entry sweep spanning −$5,640 to +$2,307. */}
                        <span className="mt-0.5 block text-[10px] text-muted">
                          {g.medianNet == null ? (
                            "not yet run"
                          ) : (
                            <>
                              median{" "}
                              <span className={g.medianNet >= 0 ? "text-green" : "text-red"}>
                                {fmtUsd(g.medianNet)}
                              </span>
                              {g.scored > 1 && (
                                <>
                                  {" "}
                                  · range {fmtUsd(g.worstNet!)}…{fmtUsd(g.bestNet!)}
                                </>
                              )}
                              {g.scored < g.strategies.length && (
                                <> · {g.strategies.length - g.scored} unrun</>
                              )}
                            </>
                          )}
                        </span>
                      </span>
                    </button>
                    {!isCollapsed && (
                      <div className="mt-1 space-y-1">
                        {g.strategies.map((s) => (
                          <Row
                            key={s.id}
                            strategy={s}
                            selected={selectedId === s.id}
                            onSelect={onSelect}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            : sorted.map((s) => (
                <Row
                  key={s.id}
                  strategy={s}
                  selected={selectedId === s.id}
                  onSelect={onSelect}
                  showFamily
                />
              ))}
        </div>
      )}
    </div>
  );
}

function Row({
  strategy: s,
  selected,
  onSelect,
  showFamily = false,
}: {
  strategy: Strategy;
  selected: boolean;
  onSelect: (id: string) => void;
  showFamily?: boolean;
}) {
  const c = classify(s);
  const untradeable = !c.safety.tradeable;
  return (
    <button
      onClick={() => onSelect(s.id)}
      data-testid="strategy-row"
      // The full name, description and key config in one native tooltip, so the
      // operator never has to open a strategy just to learn what it is. Native
      // `title` on purpose — same reasoning as InfoTip: it cannot be clipped by a
      // scrolling ancestor and is accessible without extra wiring.
      title={rowTooltip(s, c)}
      style={untradeable ? COUNTERFACTUAL_ROW_STYLE : undefined}
      className={`w-full rounded-lg border px-2 py-1.5 text-left transition-colors ${
        selected
          ? "border-blue/60 bg-blue/10"
          : "border-transparent hover:border-border hover:bg-bg/60"
      } ${untradeable ? "opacity-70" : ""}`}
    >
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 text-[10px] tabular-nums text-muted">
          <span data-testid="strategy-rank">{s.rank ?? "—"}</span>
        </span>
        <span
          className={`min-w-0 flex-1 truncate text-sm font-medium ${
            untradeable ? "text-muted line-through decoration-red/40" : "text-text"
          }`}
        >
          {s.name}
        </span>
        <span
          className={`shrink-0 text-sm tabular-nums ${
            s.net_pnl == null ? "text-muted" : s.net_pnl >= 0 ? "text-green" : "text-red"
          }`}
        >
          {s.net_pnl == null ? "—" : fmtUsd(s.net_pnl)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        <SafetyBadges classification={c} compact />
        <PhaseBadge phase={s.phase} />
        <DsrBadge dsr={s.dsr} />
        {showFamily && <FamilyBadge classification={c} />}
        <span className="ml-auto">
          <BacktestStatusBadge status={s.status} />
        </span>
      </div>
    </button>
  );
}

/** Multi-line hover text: full name, what the run is, and the config that defines
 *  it. Newlines render in the native tooltip on every platform we target. */
export function rowTooltip(s: Strategy, c: Classification): string {
  const config = [
    `Family: ${c.familyLabel}`,
    `Span: ${c.spanText}${c.spanName ? ` — ${c.spanName}` : ""}`,
    `Entry |Z|≥${s.entry_threshold} · Exit |Z|<${s.exit_threshold} · Stop |Z|≥${s.stop_threshold}`,
    `p-value ≤${s.pvalue_max} · half-life ≤${s.max_half_life_h}h · Z-window ${s.zscore_window}`,
    `Scan ${s.scan_window_days}d / Trade ${s.trade_window_days}d · $${s.usd_per_trade}/trade`,
    `Costs: ${s.taker_fee_pct}% fee + ${s.slippage_pct}% slippage per side`,
    `Trades ${s.total_trades}${s.win_rate != null ? ` · Win rate ${(s.win_rate * 100).toFixed(0)}%` : ""}`,
  ].join("\n");

  // The curated/operator text explains intent; the generated diff pins down what
  // actually differs. Show both unless they are the same string.
  const prose =
    c.description === c.autoDescription
      ? c.description
      : `${c.description}\n\n${c.autoDescription}`;

  return [s.name, prose, config].join("\n\n");
}

function Control({
  label,
  tip,
  children,
}: {
  label: string;
  tip?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[10px] uppercase tracking-wider text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </span>
      {children}
    </label>
  );
}

const selectClass =
  "w-full rounded border border-border bg-card px-1.5 py-1 text-[11px] text-text focus:border-blue/60 focus:outline-none";

export function BacktestStatusBadge({ status }: { status: BacktestStatus }) {
  const tone =
    status === "COMPLETED"
      ? "bg-green/20 text-green"
      : status === "RUNNING"
        ? "bg-blue/20 text-blue"
        : status === "PAUSED"
          ? "bg-yellow/20 text-yellow"
          : status === "FAILED"
            ? "bg-red/20 text-red"
            : "bg-muted/20 text-muted"; // PENDING / STOPPED
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="bt-status-badge"
    >
      {status}
    </span>
  );
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
