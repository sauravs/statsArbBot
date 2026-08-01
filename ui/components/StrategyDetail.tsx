"use client";

import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  fetchBacktestCosts,
  fetchBacktestTrades,
  type BacktestCostBucket,
  type BacktestCostSummary,
  type BacktestTrade,
  type BacktestWindow,
  type Strategy,
} from "@/lib/api";
import { BacktestStatusBadge } from "./StrategyList";
import { FamilyBadge, SafetyBadges } from "./SafetyBadges";
import { FAMILY_DESCRIPTIONS, classify } from "@/lib/strategyTaxonomy";
import InfoTip from "./InfoTip";
import { reasonLabel, reasonHint, reasonBadgeStyle, reasonColor } from "@/lib/exitReason";
import {
  FEES_NOTE,
  FUNDING_NOTE,
  SLIPPAGE_NOTE,
  costBreakdown,
} from "@/lib/tradeCosts";

// The exit-reason mix (issue #79) is coloured by the shared P&L-neutral scheme
// (`reasonColor`) so a reason reads the same everywhere: Reverted = blue (planned
// exit), Z-stop = red (breakdown), Time-stop = amber (stale), Window end = grey.
// Health is conveyed by the summary line + its tone, not by a green slice.

/** A one-line read of the exit mix — a strategy-health hint, not a verdict. */
function exitHealth(
  data: { reason: string; count: number }[],
  total: number,
): { tone: string; text: string } | null {
  if (total === 0) return null;
  const share = (r: string) =>
    ((data.find((d) => d.reason === r)?.count ?? 0) / total) * 100;
  const tp = share("TAKE_PROFIT");
  const sz = share("STOP_LOSS_ZSCORE");
  const st = share("STOP_LOSS_TIME");
  const ew = share("END_OF_WINDOW");
  if (sz >= 20)
    return {
      tone: "text-red",
      text: `${sz.toFixed(0)}% hit the Z-stop — watch for cointegration breakdown.`,
    };
  if (ew >= 25)
    return {
      tone: "text-yellow",
      text: `${ew.toFixed(0)}% force-closed at window end — the trade window may be too short for the spread to revert.`,
    };
  if (st >= 25)
    return {
      tone: "text-yellow",
      text: `${st.toFixed(0)}% closed on the Time-stop — the spread reverts slowly (positions near the half-life cap).`,
    };
  if (tp >= 60)
    return {
      tone: "text-green",
      text: `${tp.toFixed(0)}% Reverted (take-profit) — healthy mean-reversion.`,
    };
  return { tone: "text-muted", text: "Mixed exit profile." };
}

// Detail for one strategy's walk-forward backtest (PRD F8.4): run/pause/stop/delete
// controls, headline metrics, the equity curve, the per-window walk-forward table,
// per-pair P&L, exit reasons, and the generated markdown report (reports viewer).
export default function StrategyDetail({
  strategy,
  busy,
  onRun,
  onPause,
  onPaperTrade,
  onStop,
  onDelete,
}: {
  strategy: Strategy;
  busy: boolean;
  onRun: () => void;
  onPause: () => void;
  /** Launch a linked paper-trading session from this strategy (Phase 5). */
  onPaperTrade?: (s: Strategy) => void;
  onStop: () => void;
  onDelete: () => void;
}) {
  const s = strategy;
  const running = s.status === "RUNNING";
  const curve = (s.equity_curve ?? []).map((p) => ({ t: p.t, equity: p.equity }));
  const perWindow = s.per_window ?? [];
  const perPair = Object.entries(s.per_pair_pnl ?? {}).sort((a, b) => b[1].net_pnl - a[1].net_pnl);
  const exitReasons = Object.entries(s.exit_reasons ?? {}).sort((a, b) => b[1] - a[1]);
  const canResume = s.status === "PAUSED";
  // Same classification the list uses, so a counterfactual is unmistakable wherever
  // the operator is looking (docs/QA.md 2026-07-22).
  const cls = classify(s);
  const familyDoc = FAMILY_DESCRIPTIONS[cls.family];
  // Clamp to [0,100] and guard NaN so a transient bad progress value can't render
  // "NaN%" or an invalid CSS width.
  const pct = Math.max(0, Math.min(100, Math.round((s.progress || 0) * 100)));

  // Cost decomposition (Phase-4 Task A, Slice A2). Fetched once per strategy and
  // shared: the run-level total renders here, and each window's bucket is handed
  // to its blotter — so drilling into five windows costs one request, not five.
  const [costs, setCosts] = useState<BacktestCostSummary | null>(null);
  useEffect(() => {
    let live = true;
    setCosts(null);
    // Only a finished run has a stable decomposition; mid-sweep the totals move.
    if (running || s.total_trades === 0) return;
    fetchBacktestCosts(s.id)
      .then((r) => live && setCosts(r))
      .catch(() => live && setCosts(null)); // non-fatal: the panel just stays hidden
    return () => {
      live = false;
    };
  }, [s.id, running, s.total_trades]);
  const windowCosts = useMemo(() => {
    const m = new Map<number, BacktestCostBucket>();
    for (const w of costs?.per_window ?? []) m.set(w.window_index, w);
    return m;
  }, [costs]);

  return (
    <div className="space-y-6" data-testid="strategy-detail">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">
            {s.name}
            {s.rank != null && (
              <span className="ml-2 text-xs text-muted" data-testid="bt-rank">
                rank #{s.rank}
              </span>
            )}
          </h2>
          <BacktestStatusBadge status={s.status} />
        </div>
        {/* Loud tier, immediately under the name — the two qualifiers that decide
            whether this run's headline number means anything. */}
        <div className="mb-3 mt-2">
          <SafetyBadges classification={cls} />
        </div>

        {s.description && <p className="mb-3 text-xs text-muted">{s.description}</p>}

        {(running || s.status === "PAUSED") && (
          <div className="mb-4" data-testid="bt-progress">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>
                {running ? "Sweeping…" : "Paused at"} {s.processed_windows}/{s.total_windows} windows
              </span>
              <span className="tabular-nums">{pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
              <div
                className="h-full bg-blue transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {s.status === "FAILED" && s.error && (
          <p className="mb-4 text-sm text-red" data-testid="bt-failed-error">
            {s.error}
          </p>
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Metric label="Category" value={cls.familyLabel} testid="bt-category" small
            tip={`${familyDoc.what}\n\n${familyDoc.finding}${familyDoc.analogy ? `\n\n${familyDoc.analogy}` : ""}`} />
          <Metric label="Net P&L" value={s.net_pnl != null ? fmtUsd(s.net_pnl) : "—"}
            tone={s.net_pnl != null ? (s.net_pnl >= 0 ? "green" : "red") : undefined}
            testid="bt-net-pnl"
            tip="Total profit/loss across every closed trade in all walk-forward windows, after slippage and fees." />
          <Metric label="Final" value={s.final_capital != null ? fmtUsd(s.final_capital) : "—"} testid="bt-final-cap"
            tip="Ending equity of the run — starting capital plus net P&L." />
          <Metric label="Trades" value={String(s.total_trades)} testid="bt-total-trades"
            tip="Number of pair trades opened and closed across all windows." />
          <Metric label="Win rate" value={s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : "—"} testid="bt-win-rate"
            tip="Share of closed trades that ended profitable (net of costs)." />
        </div>

        {costs && costs.total.trades > 0 && (
          <div className="mt-4 sm:max-w-xs">
            <CostDecomposition
              bucket={costs.total}
              title="Cost decomposition · whole run"
              testid="bt-cost-summary"
            />
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted">
          <span>
            Scan {s.scan_window_days}d / Trade {s.trade_window_days}d
            <InfoTip text="Each walk-forward window scans this many days of history to pick cointegrated pairs, then trades them out-of-sample over the next N days — then the window steps forward." />
          </span>
          <span>
            Z-window {s.zscore_window}
            <InfoTip text="Rolling lookback, in bars, for the spread's z-score — the standardisation window the entry/exit signals read." />
          </span>
          <span>
            Entry |Z|≥{s.entry_threshold}
            <InfoTip text="Open a pair when the spread's |z-score| reaches this — the divergence that triggers a market-neutral trade." />
          </span>
          <span>
            Exit |Z|&lt;{s.exit_threshold}
            <InfoTip text="Take-profit: close once |z-score| falls back below this, i.e. the spread has reverted toward its mean." />
          </span>
          <span>
            Stop |Z|≥{s.stop_threshold}
            <InfoTip text="Hard stop: close at a loss if |z-score| diverges to this, signalling a likely cointegration breakdown." />
          </span>
          <span>
            Windows {s.processed_windows}/{s.total_windows}
            <InfoTip text="Walk-forward windows processed / total — each is an independent scan→trade slice stepped through history." />
          </span>
        </div>

        {/* Controls */}
        <div className="mt-5 flex flex-wrap gap-2">
          {!running && (
            <button
              onClick={onRun}
              disabled={busy}
              className="rounded-lg bg-green/20 px-3 py-1.5 text-xs font-medium text-green transition-colors hover:bg-green/30 disabled:opacity-40"
              data-testid="bt-run-btn"
            >
              {canResume ? "Resume" : s.status === "PENDING" ? "Run backtest" : "Re-run"}
            </button>
          )}
          {running && (
            <>
              <button
                onClick={onPause}
                disabled={busy}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-yellow/60 hover:text-yellow disabled:opacity-40"
                data-testid="bt-pause-btn"
              >
                Pause
              </button>
              <button
                onClick={onStop}
                disabled={busy}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red/60 hover:text-red disabled:opacity-40"
                data-testid="bt-stop-btn"
              >
                Stop
              </button>
            </>
          )}
          {!running && onPaperTrade && (
            <button
              onClick={() => onPaperTrade(s)}
              disabled={busy}
              className="rounded-lg border border-amber/50 bg-amber/10 px-3 py-1.5 text-xs font-medium text-amber transition-colors hover:bg-amber/20 disabled:opacity-40"
              data-testid="bt-paper-trade-btn"
              title={
                "Prefill a real-time simulation from this strategy's parameters and link the two, " +
                "so this row is marked 'In sim' while it runs.\n\n" +
                "Virtual money only. A paper run rehearses the plumbing — it is not evidence of edge " +
                "(docs/PHASE5_PAPER_TRADING_PLAN.md §2)."
              }
            >
              Paper-trade this
            </button>
          )}
          {!running && (
            <button
              onClick={onDelete}
              disabled={busy}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red/60 hover:text-red disabled:opacity-40"
              data-testid="bt-delete-btn"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {/* What this run IS — the context that a net-P&L number alone cannot carry
          (docs/QA.md 2026-07-22). Curated per family where the campaign produced a
          finding; the config diff underneath is generated for every run, so even an
          unrecognised strategy explains itself. */}
      <div className="rounded-xl border border-border bg-card p-5" data-testid="bt-about">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="text-xs uppercase tracking-wider text-muted">About this run</h3>
          <FamilyBadge classification={cls} />
        </div>

        <dl className="space-y-3 text-sm">
          <div>
            <dt className="text-xs font-medium text-muted">What this tests</dt>
            <dd className="mt-0.5 text-text">{familyDoc.what}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-muted">What it means</dt>
            <dd className="mt-0.5 text-text">{familyDoc.finding}</dd>
          </div>
          {familyDoc.analogy && (
            <div>
              <dt className="text-xs font-medium text-muted">In plain terms</dt>
              <dd className="mt-0.5 italic text-muted">{familyDoc.analogy}</dd>
            </div>
          )}
          <div>
            <dt className="text-xs font-medium text-muted">
              This run specifically
              <InfoTip text="Generated by diffing this strategy's configuration against the rank-#1 baseline (entry |Z| 3.0, exit 0.5, stop 4.0, p-value 0.01, half-life 72h, 21d scan / 7d trade, 0.05% fee + 0.05% slippage)." />
            </dt>
            <dd className="mt-0.5 text-text">{cls.autoDescription}</dd>
          </div>
          {!cls.safety.tradeable && (
            <p className="rounded-lg border border-red/40 bg-red/10 p-3 text-xs text-red">
              This run&apos;s costs are below anything you could execute at, so its P&amp;L is a
              measurement of the signal, not a forecast of your money. Compare it only against
              other diagnostics.
            </p>
          )}
          {cls.safety.tradeable && cls.safety.span !== "OUT_OF_SAMPLE" && (
            <p className="rounded-lg border border-yellow/40 bg-yellow/10 p-3 text-xs text-yellow">
              This run&apos;s span overlaps the window the parameters were tuned on, so a good
              result here is expected rather than evidence. The out-of-sample spans (s2–s4) are
              the test that counts.
            </p>
          )}
        </dl>
      </div>

      {/* Why-no-trades diagnostic (issue #87): a COMPLETED run with 0 trades
          renders a flat $0 curve + empty panels; explain whether it's the pair
          filter or the entry that bit, and suggest concrete looser values. */}
      {s.status === "COMPLETED" && s.total_trades === 0 && <NoTradesDiagnostic s={s} />}

      {/* Equity curve */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
          Equity Curve
          <InfoTip text="Account equity over time across all windows — the compounded result of every trade in the run." />
        </h2>
        {curve.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="bt-equity-empty">
            No equity data yet.
          </p>
        ) : (
          <div className="h-64" data-testid="bt-equity-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curve} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid stroke="#21262d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="t"
                  tickFormatter={(t) => new Date(t * 1000).toISOString().slice(5, 10)}
                  stroke="#8b949e"
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                />
                <YAxis
                  stroke="#8b949e"
                  tick={{ fontSize: 11 }}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => `$${Math.round(v).toLocaleString()}`}
                  width={70}
                />
                <Tooltip
                  contentStyle={{
                    background: "#12141a",
                    border: "1px solid #21262d",
                    borderRadius: "0.5rem",
                    color: "#e4e6ea",
                    fontSize: "0.8rem",
                  }}
                  labelFormatter={(t) => new Date(Number(t) * 1000).toISOString().slice(0, 16).replace("T", " ")}
                  formatter={(v: number) => [fmtUsd(v), "Equity"]}
                />
                <Line type="monotone" dataKey="equity" stroke="#00d4a1" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Walk-forward windows — each row expands into its per-trade blotter (#162) */}
      <WalkForwardWindows strategyId={s.id} windows={perWindow} windowCosts={windowCosts} />

      {/* Per-pair P&L + exit reasons */}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
            Per-Pair P&amp;L
            <InfoTip text="Net result per traded pair across the whole run — which pairs carried or dragged the strategy." />
          </h2>
          {perPair.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted" data-testid="bt-perpair-empty">
              No closed trades.
            </p>
          ) : (
            <table className="w-full text-sm" data-testid="bt-perpair-table">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                  <th className="px-2 py-2 text-left">Pair</th>
                  <th className="px-2 py-2 text-right">Trades</th>
                  <th className="px-2 py-2 text-right">Wins</th>
                  <th className="px-2 py-2 text-right">Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {perPair.map(([pair, b]) => (
                  <tr key={pair} className="border-b border-border/50">
                    <td className="px-2 py-2 font-medium text-text">{pair}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{b.trades}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{b.wins}</td>
                    <td className={`px-2 py-2 text-right tabular-nums ${b.net_pnl >= 0 ? "text-green" : "text-red"}`}>
                      {fmtUsd(b.net_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
            Exit Reasons
            <InfoTip text="Why trades closed — Reverted (take-profit), Z-stop, Time-stop, or Window end. The mix is a strategy-health signal, independent of P&L." />
          </h2>
          {exitReasons.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted" data-testid="bt-exits-empty">
              No exits yet.
            </p>
          ) : (
            (() => {
              const total = exitReasons.reduce((sum, [, c]) => sum + c, 0);
              const pieData = exitReasons.map(([reason, count]) => ({
                reason,
                count,
                pct: total ? (count / total) * 100 : 0,
              }));
              const health = exitHealth(pieData, total);
              return (
                <div data-testid="bt-exits">
                  <div className="h-40" data-testid="bt-exits-donut">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={pieData}
                          dataKey="count"
                          nameKey="reason"
                          innerRadius={42}
                          outerRadius={62}
                          paddingAngle={2}
                          stroke="none"
                        >
                          {pieData.map((d) => (
                            <Cell key={d.reason} fill={reasonColor(d.reason)} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{
                            background: "#12141a",
                            border: "1px solid #21262d",
                            borderRadius: "0.5rem",
                            fontSize: "0.8rem",
                          }}
                          itemStyle={{ color: "#e4e6ea" }}
                          labelStyle={{ color: "#e4e6ea" }}
                          formatter={(
                            v: number,
                            _n,
                            p: { payload?: { pct: number; reason: string } },
                          ) => [
                            `${v} (${(p.payload?.pct ?? 0).toFixed(0)}%)`,
                            reasonLabel(p.payload?.reason ?? ""),
                          ]}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className="mt-3 space-y-1.5" data-testid="bt-exits-list">
                    {pieData.map((d) => (
                      <li
                        key={d.reason}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="flex items-center gap-2 text-muted">
                          <span
                            className="inline-block h-2 w-2 shrink-0 rounded-full"
                            style={{ background: reasonColor(d.reason) }}
                          />
                          {reasonLabel(d.reason)}
                        </span>
                        <span className="tabular-nums text-text">
                          {d.count} · {d.pct.toFixed(0)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                  {health && (
                    <p className={`mt-3 text-xs ${health.tone}`} data-testid="bt-exits-health">
                      {health.text}
                    </p>
                  )}
                </div>
              );
            })()
          )}
        </div>
      </div>

      {/* Report viewer (F8.3) */}
      {s.report_md && (
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
            Report
            <InfoTip text="The generated markdown summary — parameters, aggregates, and per-window results for this run." />
          </h2>
          <pre
            className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-bg p-4 text-xs leading-relaxed text-muted"
            data-testid="bt-report"
          >
            {s.report_md}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Walk-forward windows + per-trade blotter (issue #162) ────────────────────
// Each window row expands into a paginated blotter of that window's closed trades
// (lazy-loaded on first open), so the operator can see where/when each trade
// entered & exited on the spread (Z + leg prices) and the exit rationale. Trades
// are scoped per window server-side, so a 500-trade window loads a page at a time
// rather than dumping everything at once.
const TRADES_PAGE = 25;

function WalkForwardWindows({
  strategyId,
  windows,
  windowCosts,
}: {
  strategyId: string;
  windows: BacktestWindow[];
  /** Per-window cost decomposition, fetched once by the parent (Slice A2). */
  windowCosts: Map<number, BacktestCostBucket>;
}) {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Walk-Forward Windows
        <InfoTip text="Per-window breakdown: each row is one scan→trade slice with the pairs it selected, trades taken, and net P&L. Click a row to see that window's individual trades — where/when each entered & exited, and why." />
      </h2>
      {windows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted" data-testid="bt-perwindow-empty">
          No windows processed yet.
        </p>
      ) : (
        <table className="w-full text-sm" data-testid="bt-perwindow-table">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
              <th className="px-2 py-2 text-left">#</th>
              <th className="px-2 py-2 text-left">
                Scan (formation)
                <InfoTip text="The formation window the cointegration scan reads to SELECT pairs — no trading happens here." />
              </th>
              <th className="px-2 py-2 text-left">
                Trade (test)
                <InfoTip text="The out-of-sample window where the selected pairs are traded (data the scan never saw). Trade windows tile edge-to-edge across history." />
              </th>
              <th className="px-2 py-2 text-right">Pairs</th>
              <th className="px-2 py-2 text-right">Trades</th>
              <th className="px-2 py-2 text-right">Net P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((w) => {
              const isOpen = open === w.index;
              const hasTrades = w.trades > 0;
              return (
                <Fragment key={w.index}>
                  <tr
                    className={`border-b border-border/50 ${hasTrades ? "cursor-pointer hover:bg-bg/50" : ""}`}
                    data-testid="bt-perwindow-row"
                    onClick={() => hasTrades && setOpen(isOpen ? null : w.index)}
                    aria-expanded={isOpen}
                  >
                    <td className="px-2 py-2 tabular-nums text-muted">
                      {hasTrades && (
                        <span className="mr-1 inline-block w-3 text-muted">{isOpen ? "▾" : "▸"}</span>
                      )}
                      {w.index}
                    </td>
                    <td className="px-2 py-2 text-xs text-muted">
                      {w.scan_start.slice(0, 10)} → {w.scan_end.slice(0, 10)}
                    </td>
                    <td className="px-2 py-2 text-xs text-muted">
                      {w.trade_start.slice(0, 10)} → {w.trade_end.slice(0, 10)}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{w.pairs}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">{w.trades}</td>
                    <td className={`px-2 py-2 text-right tabular-nums ${w.net_pnl >= 0 ? "text-green" : "text-red"}`}>
                      {fmtUsd(w.net_pnl)}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr data-testid="bt-window-blotter">
                      <td colSpan={6} className="bg-bg/40 px-2 py-3">
                        <TradeBlotter
                          strategyId={strategyId}
                          windowIndex={w.index}
                          costs={windowCosts.get(w.index)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TradeBlotter({
  strategyId,
  windowIndex,
  costs,
}: {
  strategyId: string;
  windowIndex: number;
  /** This window's Σ decomposition — summarises the whole window, not just the
   *  25 trades on the current page (Slice A2). */
  costs?: BacktestCostBucket;
}) {
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  // Server-side "losing take-profits" filter: reason=TAKE_PROFIT AND net_pnl<0 —
  // the cohort where the thesis worked (spread reverted) but costs ate the trade.
  const [losingTpOnly, setLosingTpOnly] = useState(false);

  const load = async (nextOffset: number, losingTp: boolean = losingTpOnly) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchBacktestTrades(strategyId, {
        window: windowIndex,
        limit: TRADES_PAGE,
        offset: nextOffset,
        outcome: losingTp ? "losing_tp" : undefined,
      });
      setTrades(res.trades);
      setTotal(res.total);
      setOffset(nextOffset);
      setLoadedOnce(true);
    } catch {
      setError("Could not load trades for this window.");
    } finally {
      setLoading(false);
    }
  };

  const toggleLosingTp = () => {
    const next = !losingTpOnly;
    setLosingTpOnly(next);
    void load(0, next); // reset to the first page under the new filter
  };

  // Lazy-load the first page when the blotter mounts (i.e. the row is opened).
  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading && !loadedOnce) {
    return <p className="py-3 text-center text-xs text-muted" data-testid="bt-blotter-loading">Loading trades…</p>;
  }
  if (error) {
    return <p className="py-3 text-center text-xs text-red">{error}</p>;
  }
  // Genuinely-empty window (no trades at all, filter off) → keep the terse note.
  if (loadedOnce && total === 0 && !losingTpOnly) {
    return <p className="py-3 text-center text-xs text-muted">No trades in this window.</p>;
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + TRADES_PAGE, total);

  return (
    <div data-testid="bt-blotter">
      {costs && costs.trades > 0 && (
        // The window's totals, not the page's — the blotter paginates 25 at a
        // time, so summing what is on screen would understate every column.
        <div className="mb-2 sm:max-w-xs">
          <CostDecomposition
            bucket={costs}
            title={`Cost decomposition · window ${windowIndex}`}
            testid="bt-window-cost-summary"
            compact
          />
        </div>
      )}
      <div className="mb-2 flex items-center gap-2 text-[11px]">
        <button
          type="button"
          onClick={toggleLosingTp}
          aria-pressed={losingTpOnly}
          disabled={loading}
          data-testid="bt-blotter-filter-losing-tp"
          className={`rounded border px-2 py-0.5 disabled:opacity-40 ${
            losingTpOnly
              ? "border-yellow/60 bg-yellow/10 text-yellow"
              : "border-border text-muted hover:bg-bg/50"
          }`}
        >
          {losingTpOnly ? "✓ " : ""}Losing take-profits
        </button>
        <span className="text-muted/70">
          <InfoTip text="Show only 'Reverted' (take-profit) exits that still closed at a net loss — the spread reverted but fees + funding turned the trade red. The interesting cohort for tuning costs / half-life." />
        </span>
        {/* Make the identity discoverable without hovering every column header. */}
        <span className="ml-auto text-muted/70" data-testid="bt-blotter-cost-legend">
          Gross + Fees + Funding = Net
          <InfoTip text={SLIPPAGE_NOTE} />
        </span>
      </div>
      {total === 0 ? (
        <p className="py-3 text-center text-xs text-muted" data-testid="bt-blotter-empty">
          No losing take-profits in this window.
        </p>
      ) : (
      <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1180px] text-xs" data-testid="bt-blotter-table">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted">
              <th className="px-2 py-1.5 text-left">Pair</th>
              <th className="px-2 py-1.5 text-center">
                Dir
                <InfoTip text="Trade direction, in PAIR order (base/quote). L/S = Long base, Short quote — entered when z<0 (spread below its mean, base relatively cheap). S/L = Short base, Long quote — entered when z>0. A pair trade is always market-neutral: long one leg, short the other." />
              </th>
              <th className="px-2 py-1.5 text-left">Entry (t · Z · px)</th>
              <th className="px-2 py-1.5 text-left">Exit (t · Z · px)</th>
              <th className="px-2 py-1.5 text-right">
                Hold
                <InfoTip text="How long the position was open, in hours. Funding accrues over this time, so a long hold is also a bigger funding bill (or credit) — read it together with the Funding column." />
              </th>
              <th className="px-2 py-1.5 text-right">
                Gross
                <InfoTip text={SLIPPAGE_NOTE} />
              </th>
              <th className="px-2 py-1.5 text-right">
                Fees
                <InfoTip text={FEES_NOTE} />
              </th>
              <th className="px-2 py-1.5 text-right">
                Funding
                <InfoTip text={FUNDING_NOTE} />
              </th>
              <th className="px-2 py-1.5 text-right">
                Net P&amp;L
                <InfoTip text="What the trade actually made or lost: Gross + Fees + Funding. Slippage and market impact are not a separate column — they are charged at the fill price, so they are already inside Gross." />
              </th>
              <th className="px-2 py-1.5 text-center">
                Outcome
                <InfoTip text="Did the trade make money? Driven purely by Net P&L sign — kept separate from Reason, because the two are independent: a 'Reverted' (take-profit) exit can still be a Loss after fees & funding." />
              </th>
              <th className="px-2 py-1.5 text-left">
                Reason
                <InfoTip text="Why the position closed — a signal rule: Reverted (|z| fell back inside the exit band, i.e. take-profit), Z-stop (|z| diverged past the stop), or Time-stop (held too long). This is the exit TRIGGER, not the dollar result: a Reverted exit can still be a net loss after fees & funding — see Net P&L / Outcome." />
              </th>
              <th className="px-2 py-1.5 text-center">
                Chart
                <InfoTip text="Open this trade on a 4-panel pair chart (price, spread, z-score) over its test window, with the entry and exit marked — like the Manual Trading view. Opens in a new tab." />
              </th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const c = costBreakdown(t);
              return (
              <tr key={t.id} className="border-b border-border/40" data-testid="bt-blotter-row">
                <td className="whitespace-nowrap px-2 py-1.5 text-text">
                  {shortMkt(t.base_market)}/{shortMkt(t.quote_market)}
                </td>
                <td className="px-2 py-1.5 text-center tabular-nums text-muted">{dirShort(t.direction)}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-muted">
                  <span className="text-text">{fmtTime(t.entry_time)}</span>
                  {" · "}z={fmtZ(t.entry_z)}
                  {" · "}
                  {fmtPx(t.entry_base_px)}/{fmtPx(t.entry_quote_px)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-muted">
                  <span className="text-text">{fmtTime(t.exit_time)}</span>
                  {" · "}z={fmtZ(t.exit_z)}
                  {" · "}
                  {fmtPx(t.exit_base_px)}/{fmtPx(t.exit_quote_px)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-muted" data-testid="bt-blotter-hold">
                  {Math.round(c.holdHours)}h
                </td>
                {/* Cost decomposition (Phase-4 Task A): gross + fees + funding = net.
                    Slippage/impact are inside gross — see SLIPPAGE_NOTE. */}
                <td
                  className={`px-2 py-1.5 text-right tabular-nums ${c.gross >= 0 ? "text-green/80" : "text-red/80"}`}
                  data-testid="bt-blotter-gross"
                >
                  {fmtUsd(c.gross)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-muted" data-testid="bt-blotter-fees">
                  {fmtUsd(c.fees)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right tabular-nums ${c.funding >= 0 ? "text-green/80" : "text-red/80"}`}
                  data-testid="bt-blotter-funding"
                >
                  {fmtUsd(c.funding)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right tabular-nums ${c.net >= 0 ? "text-green" : "text-red"}`}
                  data-testid="bt-blotter-net"
                >
                  {fmtUsd(c.net)}
                  {!c.reconciles && (
                    <span
                      className="ml-1 cursor-help text-yellow"
                      title="This row's components do not add up to its stored net P&L — treat the breakdown as unreliable for this trade."
                      data-testid="bt-blotter-mismatch"
                    >
                      ⚠
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-center">
                  {t.net_pnl > 0 ? (
                    <span className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] text-green" style={{ backgroundColor: "#00d4a11a" }} data-testid="bt-blotter-outcome">
                      ✓ Win
                    </span>
                  ) : t.net_pnl < 0 ? (
                    <span className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] text-red" style={{ backgroundColor: "#ff47571a" }} data-testid="bt-blotter-outcome">
                      ✗ Loss
                    </span>
                  ) : (
                    <span className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] text-muted" style={{ backgroundColor: "#8b949e1a" }} data-testid="bt-blotter-outcome">
                      Flat
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  <span
                    className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px]"
                    style={reasonBadgeStyle(t.exit_reason)}
                    title={reasonHint(t.exit_reason)}
                    data-testid="bt-blotter-reason"
                  >
                    {reasonLabel(t.exit_reason)}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-center">
                  <a
                    href={`/dashboard/backtest/trade/${encodeURIComponent(strategyId)}/${encodeURIComponent(t.id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="whitespace-nowrap rounded border border-border px-1.5 py-0.5 text-[10px] text-blue hover:bg-bg/50"
                    data-testid="bt-blotter-chart-link"
                  >
                    Chart ↗
                  </a>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
        <span data-testid="bt-blotter-range">
          {from}–{to} of {total} trade{total === 1 ? "" : "s"}
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            className="rounded border border-border px-2 py-0.5 disabled:opacity-40"
            disabled={loading || offset === 0}
            onClick={() => load(Math.max(0, offset - TRADES_PAGE))}
            data-testid="bt-blotter-prev"
          >
            Prev
          </button>
          <button
            type="button"
            className="rounded border border-border px-2 py-0.5 disabled:opacity-40"
            disabled={loading || to >= total}
            onClick={() => load(offset + TRADES_PAGE)}
            data-testid="bt-blotter-next"
          >
            Next
          </button>
        </span>
      </div>
      </>
      )}
    </div>
  );
}

/**
 * Where the net went, over a set of trades (Phase-4 Task A, Slice A2). The
 * blotter answers this for ONE trade; this answers it for a window or a whole
 * run — the view that makes a campaign's results readable without scrolling
 * thousands of rows. Same identity, same helper, so the two can never disagree.
 */
function CostDecomposition({
  bucket,
  title,
  testid,
  compact = false,
}: {
  bucket: BacktestCostBucket;
  title: string;
  testid: string;
  compact?: boolean;
}) {
  const c = costBreakdown(bucket);
  const rows: { label: string; value: number; tip: string; tone: boolean }[] = [
    { label: "Gross", value: c.gross, tip: SLIPPAGE_NOTE, tone: true },
    { label: "Fees", value: c.fees, tip: FEES_NOTE, tone: false },
    { label: "Funding", value: c.funding, tip: FUNDING_NOTE, tone: true },
  ];
  return (
    <div
      className={`rounded-lg border border-border bg-bg/40 ${compact ? "p-2.5" : "p-3"}`}
      data-testid={testid}
    >
      <p className="mb-1.5 text-[10px] uppercase tracking-wider text-muted">
        {title}
        <InfoTip text="Where this run's net P&L came from: Gross + Fees + Funding = Net, summed over every closed trade. Funding scales with how long positions are held, so a long average hold shows up here as a bigger funding line." />
      </p>
      <dl className="space-y-0.5 text-xs">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-4">
            <dt className="text-muted">
              {r.label}
              <InfoTip text={r.tip} />
            </dt>
            <dd
              className={`tabular-nums ${
                !r.tone ? "text-muted" : r.value >= 0 ? "text-green/80" : "text-red/80"
              }`}
              data-testid={`${testid}-${r.label.toLowerCase()}`}
            >
              {fmtUsd(r.value)}
            </dd>
          </div>
        ))}
        <div className="flex items-baseline justify-between gap-4 border-t border-border/60 pt-1">
          <dt className="text-text">Net</dt>
          <dd
            className={`font-semibold tabular-nums ${c.net >= 0 ? "text-green" : "text-red"}`}
            data-testid={`${testid}-net`}
          >
            {fmtUsd(c.net)}
          </dd>
        </div>
      </dl>
      <p className="mt-1.5 text-[10px] text-muted/70" data-testid={`${testid}-meta`}>
        {bucket.trades.toLocaleString()} trade{bucket.trades === 1 ? "" : "s"} · avg hold{" "}
        {Math.round(bucket.avg_hold_hours)}h
        {!c.reconciles && (
          <span className="ml-1 text-yellow" title="These components do not add up to the stored net P&L.">
            ⚠
          </span>
        )}
      </p>
    </div>
  );
}

// Blotter formatting helpers.
const shortMkt = (m: string) => m.replace(/-USD$/, "");
const dirShort = (d: string) => (d === "LONG_BASE" ? "L/S" : d === "SHORT_BASE" ? "S/L" : d);
const fmtTime = (iso: string) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
const fmtZ = (z: number | null) => (z === null || z === undefined ? "—" : z.toFixed(2));
const fmtPx = (p: number | null) =>
  p === null || p === undefined ? "—" : p.toLocaleString(undefined, { maximumFractionDigits: 4 });

// Diagnostic for a COMPLETED run that placed 0 trades (issue #87). The root cause
// is almost always one (or both) of: the cointegration filter (p-value / half-life)
// admitted no pairs, or pairs were found but their rolling |Z| never reached the
// entry threshold (cointegrated ⇒ mean-reverting ⇒ Z stays bounded). We split the
// saved per_window rows into those two buckets so the operator can see which bit,
// then suggest concrete looser values anchored to this run's own params.
function NoTradesDiagnostic({ s }: { s: Strategy }) {
  const windows = s.per_window ?? [];
  const total = windows.length;
  const noPairs = windows.filter((w) => w.pairs === 0).length;
  const pairsNoTrades = windows.filter((w) => w.pairs > 0 && w.trades === 0).length;
  // Looser targets — never tighter than the current value.
  const looserP = Math.max(s.pvalue_max, 0.1);
  const looserHl = Math.max(s.max_half_life_h, 168);
  const looserEntry = Math.min(s.entry_threshold, 1.0);

  return (
    <div
      className="rounded-xl border border-yellow/30 bg-yellow/5 p-5"
      data-testid="bt-no-trades-hint"
    >
      <h2 className="mb-2 text-xs uppercase tracking-wider text-yellow">
        Why no trades?
        <InfoTip text="A completed run with 0 trades is usually conservative settings, not a bug: either the cointegration filter admitted no pairs, or pairs were found but |Z| never reached the entry threshold." />
      </h2>
      <p className="text-sm text-text">
        {total > 0 ? (
          <>
            No trades across {total} walk-forward window{total === 1 ? "" : "s"}:{" "}
            <strong className="text-yellow">{noPairs}</strong> found no cointegrated
            pairs (the p≤{s.pvalue_max} / half-life≤{s.max_half_life_h}h filter is
            strict over crypto perps), and{" "}
            <strong className="text-yellow">{pairsNoTrades}</strong> found pairs but
            the rolling |Z| never reached the {s.entry_threshold} entry. This is
            expected with conservative settings — not a defect.
          </>
        ) : (
          <>
            No trades were placed — the pair filter likely admitted nothing, or the
            |Z| never reached the {s.entry_threshold} entry. Expected with
            conservative settings, not a defect.
          </>
        )}
      </p>
      <p className="mt-3 text-xs uppercase tracking-wider text-muted">Try loosening</p>
      <ul className="mt-1.5 space-y-1 text-sm text-muted" data-testid="bt-no-trades-suggestions">
        <li>
          • <span className="text-text">Pair filter</span> — p-value {s.pvalue_max} →{" "}
          {looserP}, half-life {s.max_half_life_h}h → {looserHl}h (admits more,
          slower-reverting pairs).
        </li>
        <li>
          • <span className="text-text">Entry</span> — |Z| {s.entry_threshold} →{" "}
          {looserEntry} (keep exit {s.exit_threshold}, stop {s.stop_threshold}), or
          entry 0.5 / exit 0.3 to almost always trigger.
        </li>
        <li>
          • <span className="text-text">Trade window</span> — {s.trade_window_days}d →
          45–60d to give the spread more time to revert.
        </li>
      </ul>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
  testid,
  tip,
  small = false,
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
  testid: string;
  tip?: string;
  /** For word values (the category) rather than numbers — the headline size is
   *  sized for figures and wraps badly on a phrase. */
  small?: boolean;
}) {
  const color = tone === "green" ? "text-green" : tone === "red" ? "text-red" : "text-text";
  return (
    <div>
      <p className="text-xs text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </p>
      <p
        className={`mt-1 font-semibold ${color} ${
          small ? "text-sm leading-snug" : "text-lg tabular-nums"
        }`}
        data-testid={testid}
      >
        {value}
      </p>
    </div>
  );
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
