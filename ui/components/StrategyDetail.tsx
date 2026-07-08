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
import { Fragment, useEffect, useState } from "react";
import {
  fetchBacktestTrades,
  type BacktestTrade,
  type BacktestWindow,
  type Strategy,
} from "@/lib/api";
import { BacktestStatusBadge } from "./StrategyList";
import InfoTip from "./InfoTip";

// Health-coloured palette for the exit-reason mix (issue #79): take-profit is a
// good exit (green), the z-score stop is a loss/breakdown signal (red), the time
// stop is a stale-position signal (amber), and an end-of-window force-close is
// neutral/forced (grey). Any future reason falls back to blue.
const EXIT_COLORS: Record<string, string> = {
  TAKE_PROFIT: "#00d4a1",
  STOP_LOSS_ZSCORE: "#ff4757",
  STOP_LOSS_TIME: "#ffd32a",
  END_OF_WINDOW: "#8b949e",
};
const exitColor = (reason: string) => EXIT_COLORS[reason] ?? "#4a90e2";

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
      text: `${sz.toFixed(0)}% hit the z-score stop — watch for cointegration breakdown.`,
    };
  if (ew >= 25)
    return {
      tone: "text-yellow",
      text: `${ew.toFixed(0)}% force-closed at window end — the trade window may be too short for the spread to revert.`,
    };
  if (st >= 25)
    return {
      tone: "text-yellow",
      text: `${st.toFixed(0)}% closed on the time stop — the spread reverts slowly (positions near the half-life cap).`,
    };
  if (tp >= 60)
    return {
      tone: "text-green",
      text: `${tp.toFixed(0)}% exited on take-profit — healthy mean-reversion.`,
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
  onStop,
  onDelete,
}: {
  strategy: Strategy;
  busy: boolean;
  onRun: () => void;
  onPause: () => void;
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
  // Clamp to [0,100] and guard NaN so a transient bad progress value can't render
  // "NaN%" or an invalid CSS width.
  const pct = Math.max(0, Math.min(100, Math.round((s.progress || 0) * 100)));

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

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
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
      <WalkForwardWindows strategyId={s.id} windows={perWindow} />

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
            <InfoTip text="Why trades closed — take-profit, z-score stop, time stop, or forced at the window end. The mix is a strategy-health signal." />
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
                            <Cell key={d.reason} fill={exitColor(d.reason)} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{
                            background: "#12141a",
                            border: "1px solid #21262d",
                            borderRadius: "0.5rem",
                            color: "#e4e6ea",
                            fontSize: "0.8rem",
                          }}
                          formatter={(v: number, _n, p: { payload?: { pct: number } }) => [
                            `${v} (${(p.payload?.pct ?? 0).toFixed(0)}%)`,
                            "trades",
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
                            style={{ background: exitColor(d.reason) }}
                          />
                          {d.reason}
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
}: {
  strategyId: string;
  windows: BacktestWindow[];
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
                        <TradeBlotter strategyId={strategyId} windowIndex={w.index} />
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

function TradeBlotter({ strategyId, windowIndex }: { strategyId: string; windowIndex: number }) {
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const load = async (nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchBacktestTrades(strategyId, {
        window: windowIndex,
        limit: TRADES_PAGE,
        offset: nextOffset,
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
  if (loadedOnce && total === 0) {
    return <p className="py-3 text-center text-xs text-muted">No trades in this window.</p>;
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + TRADES_PAGE, total);

  return (
    <div data-testid="bt-blotter">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-xs" data-testid="bt-blotter-table">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted">
              <th className="px-2 py-1.5 text-left">Pair</th>
              <th className="px-2 py-1.5 text-center">
                Dir
                <InfoTip text="Trade direction, in PAIR order (base/quote). L/S = Long base, Short quote — entered when z<0 (spread below its mean, base relatively cheap). S/L = Short base, Long quote — entered when z>0. A pair trade is always market-neutral: long one leg, short the other." />
              </th>
              <th className="px-2 py-1.5 text-left">Entry (t · Z · px)</th>
              <th className="px-2 py-1.5 text-left">Exit (t · Z · px)</th>
              <th className="px-2 py-1.5 text-right">Hold</th>
              <th className="px-2 py-1.5 text-right">Net P&amp;L</th>
              <th className="px-2 py-1.5 text-left">Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
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
                <td className="px-2 py-1.5 text-right tabular-nums text-muted">{Math.round(t.hold_hours)}h</td>
                <td className={`px-2 py-1.5 text-right tabular-nums ${t.net_pnl >= 0 ? "text-green" : "text-red"}`}>
                  {fmtUsd(t.net_pnl)}
                </td>
                <td className="px-2 py-1.5">
                  <span
                    className="whitespace-nowrap rounded px-1.5 py-0.5 text-[10px]"
                    style={{ color: exitColor(t.exit_reason), backgroundColor: `${exitColor(t.exit_reason)}1a` }}
                  >
                    {t.exit_reason}
                  </span>
                </td>
              </tr>
            ))}
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
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
  testid: string;
  tip?: string;
}) {
  const color = tone === "green" ? "text-green" : tone === "red" ? "text-red" : "text-text";
  return (
    <div>
      <p className="text-xs text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${color}`} data-testid={testid}>
        {value}
      </p>
    </div>
  );
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
