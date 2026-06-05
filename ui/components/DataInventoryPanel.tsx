"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelDataFetch,
  getDataFetchStatus,
  getDataInventory,
  startDataFetch,
  type DataInventory,
  type FetchStatus,
} from "@/lib/api";
import InfoTip from "./InfoTip";

// Inventory of the cached historical data (issue #80) + a fetch-by-date-range
// control (issue #81): a summary line, a per-market coverage table, and a control
// to pull new OHLCV/funding from the dYdX mainnet indexer into the cache.
export default function DataInventoryPanel() {
  const [inv, setInv] = useState<DataInventory | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    getDataInventory()
      .then(setInv)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load inventory"),
      );
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div className="space-y-6">
      <FetchControl onDone={reload} />
      {error ? (
        <p className="text-sm text-red" data-testid="data-inventory-error">
          {error}
        </p>
      ) : !inv ? (
        <p className="text-sm text-muted" data-testid="data-inventory-loading">
          Loading inventory…
        </p>
      ) : (
        <Inventory inv={inv} />
      )}
    </div>
  );
}

function Inventory({ inv }: { inv: DataInventory }) {
  const s = inv.summary;
  return (
    <div className="space-y-6" data-testid="data-inventory">
      {/* Summary */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
          Cached History
          <InfoTip text="The OHLCV/funding candles stored locally that the scan, simulation, fast-forward, and backtest engines replay. Price data is always from the dYdX mainnet indexer." />
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Markets" value={String(s.market_count)} testid="di-markets" />
          <Stat
            label="Coverage"
            value={
              s.earliest && s.latest
                ? `${fmtDate(s.earliest)} → ${fmtDate(s.latest)}`
                : "—"
            }
            testid="di-coverage"
          />
          <Stat
            label="Bars"
            value={s.total_bars.toLocaleString()}
            testid="di-bars"
            tip={`Total cached ${inv.resolution} candles across all markets.`}
          />
          <Stat
            label="Funding"
            value={`${s.funding_markets} mkts · ${s.funding_rows.toLocaleString()} rows`}
            testid="di-funding"
            tip="Cached funding-rate history — the periodic carry cost the sim/backtest cost model applies."
          />
        </div>
      </div>

      {/* Per-market coverage */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
          Per-Market Coverage
          <InfoTip text="Each cached market: how many bars, the first→last date, and completeness — the fraction of a gapless series present (low values mean gaps that can quietly degrade a backtest)." />
        </h2>
        {inv.markets.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted" data-testid="di-empty">
            No cached data. Seed it with the ingest pipeline.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="di-table">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wider text-muted">
                  <th className="px-2 py-2 text-left">Market</th>
                  <th className="px-2 py-2 text-right">Bars</th>
                  <th className="px-2 py-2 text-left">First</th>
                  <th className="px-2 py-2 text-left">Last</th>
                  <th className="px-2 py-2 text-right">Completeness</th>
                </tr>
              </thead>
              <tbody>
                {inv.markets.map((m) => (
                  <tr
                    key={m.market}
                    className="border-b border-border/50"
                    data-testid="di-row"
                  >
                    <td className="px-2 py-2 font-medium text-text">{m.market}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted">
                      {m.bars.toLocaleString()}
                    </td>
                    <td className="px-2 py-2 tabular-nums text-muted">{fmtDate(m.first)}</td>
                    <td className="px-2 py-2 tabular-nums text-muted">{fmtDate(m.last)}</td>
                    <td className="px-2 py-2">
                      <Completeness value={m.completeness} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// Fetch new OHLCV/funding by date range (issue #81). Discovers liquid markets and
// pulls the range from the dYdX mainnet indexer in the background; polls progress
// and can cancel mid-run. On completion it refreshes the inventory above.
function FetchControl({ onDone }: { onDone: () => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [status, setStatus] = useState<FetchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const st = await getDataFetchStatus();
        setStatus(st);
        if (!st.running) {
          stopPolling();
          onDoneRef.current(); // refresh inventory with the new coverage
        }
      } catch {
        /* transient — keep last status */
      }
    }, 1500);
  }, [stopPolling]);

  // Resume polling if a fetch is already running (e.g. after a page reload).
  useEffect(() => {
    getDataFetchStatus()
      .then((st) => {
        setStatus(st);
        if (st.running) poll();
      })
      .catch(() => {});
    return stopPolling;
  }, [poll, stopPolling]);

  async function onFetch() {
    if (!start || !end) {
      setError("Pick a start and end date");
      return;
    }
    if (start >= end) {
      setError("Start must be before end");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const st = await startDataFetch(`${start}T00:00:00Z`, `${end}T23:59:59Z`);
      setStatus(st);
      poll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fetch failed to start");
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    try {
      setStatus(await cancelDataFetch());
    } catch {
      /* ignore */
    }
  }

  const running = status?.running ?? false;
  const pct =
    status && status.total_markets > 0
      ? Math.round((status.markets_done / status.total_markets) * 100)
      : 0;
  const errors = status?.results.filter((r) => r.status === "error").length ?? 0;

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="data-fetch">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        Fetch History
        <InfoTip text="Pull new OHLCV + funding for a date range from the dYdX mainnet indexer into the cache. Discovers all liquid markets; merges into the range without touching data outside it. Long ranges are slow — you can cancel." />
      </h2>

      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-muted">Start date</span>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            disabled={running}
            className="bt-input"
            data-testid="fetch-start"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-muted">End date</span>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            disabled={running}
            className="bt-input"
            data-testid="fetch-end"
          />
        </label>
        {running ? (
          <button
            onClick={onCancel}
            disabled={status?.cancel_requested}
            className="rounded-lg border border-red px-3 py-2 text-xs text-red transition-colors hover:bg-red/10 disabled:opacity-40"
            data-testid="fetch-cancel"
          >
            {status?.cancel_requested ? "Stopping…" : "Cancel"}
          </button>
        ) : (
          <button
            onClick={onFetch}
            disabled={busy}
            className="rounded-lg bg-blue/20 px-3 py-2 text-xs font-medium text-blue transition-colors hover:bg-blue/30 disabled:opacity-50"
            data-testid="fetch-start-btn"
          >
            {busy ? "Starting…" : "Fetch"}
          </button>
        )}
      </div>

      {running && (
        <div className="mt-4" data-testid="fetch-progress">
          <div className="mb-1 flex justify-between text-xs text-muted">
            <span>
              Fetching {status?.current_market ?? "…"} — {status?.markets_done}/
              {status?.total_markets} markets
            </span>
            <span className="tabular-nums">{pct}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
            <div className="h-full bg-blue transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {!running && status?.finished_at && (
        <p className="mt-3 text-xs text-muted" data-testid="fetch-done">
          {status.cancelled ? "Cancelled after" : "Fetched"} {status.markets_done}/
          {status.total_markets} markets
          {errors > 0 && <span className="text-red"> · {errors} failed</span>}.
        </p>
      )}
      {(error || status?.error) && (
        <p className="mt-3 text-xs text-red" data-testid="fetch-error">
          {error || status?.error}
        </p>
      )}

      <style jsx>{`
        :global(.bt-input) {
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          background: #0a0b0d;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          color: #e4e6ea;
        }
      `}</style>
    </div>
  );
}

function Completeness({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.95 ? "#00d4a1" : value >= 0.8 ? "#ffd32a" : "#ff4757";
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-bg">
        <div className="h-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="w-9 text-right tabular-nums text-xs" style={{ color }}>
        {pct}%
      </span>
    </div>
  );
}

function Stat({
  label,
  value,
  testid,
  tip,
}: {
  label: string;
  value: string;
  testid: string;
  tip?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted">
        {label}
        {tip && <InfoTip text={tip} />}
      </p>
      <p className="mt-1 text-sm font-semibold text-text" data-testid={testid}>
        {value}
      </p>
    </div>
  );
}

/** ISO timestamp → YYYY-MM-DD. */
function fmtDate(iso: string): string {
  return iso.slice(0, 10);
}
