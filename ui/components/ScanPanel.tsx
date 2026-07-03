"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getPairs,
  getPairPrices,
  getScanStatus,
  startScan,
  stopScan,
  type PairRecord,
  type ScanStatus,
} from "@/lib/api";
import PairsTable from "./PairsTable";
import ZThresholdSlider from "./ZThresholdSlider";
import RecordManualTradeModal from "./RecordManualTradeModal";
import InfoTip from "./InfoTip";

const POLL_MS = 2000;

// Scan-policy defaults — also the Manual-Trading triage defaults (mirrors
// config.PVALUE_MAX / MAX_HALF_LIFE_H and the Backtest form).
const DEFAULT_PVALUE_MAX = "0.05";
const DEFAULT_MAX_HALF_LIFE = "72";

/**
 * Scan-time triage (#150): keep the pairs whose stored p-value / half-life meet
 * the operator's bar. Pure so it's trivial to reason about and test. An empty /
 * NaN threshold means "don't filter on that axis". This is advisory selection
 * help only — the authoritative entry gate re-validates on fresh data (#147).
 */
export function filterByQuality(
  pairs: PairRecord[],
  maxPvalue: number,
  maxHalfLife: number,
): PairRecord[] {
  return pairs.filter(
    (p) =>
      (Number.isNaN(maxPvalue) || p.p_value <= maxPvalue) &&
      (Number.isNaN(maxHalfLife) || p.half_life <= maxHalfLife),
  );
}
// Current prices are a light, best-effort read; refresh on a slow interval so a
// real dydx-mode fetch stays cheap (issue #37 PR-2).
const PRICE_POLL_MS = 20000;

export default function ScanPanel({
  onManualRecorded,
  reloadKey = 0,
}: {
  onManualRecorded?: () => void;
  /** Bumped by a data-source switch → reload pairs + prices (pairs were cleared). */
  reloadKey?: number;
}) {
  const [pairs, setPairs] = useState<PairRecord[]>([]);
  const [scannedAt, setScannedAt] = useState<string | null>(null);
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [threshold, setThreshold] = useState(1.5);
  // Scan-time triage bar (#150): narrows the table AND seeds the Record popup.
  const [maxPvalue, setMaxPvalue] = useState(DEFAULT_PVALUE_MAX);
  const [maxHalfLife, setMaxHalfLife] = useState(DEFAULT_MAX_HALF_LIFE);
  const [error, setError] = useState<string | null>(null);
  const [recordPair, setRecordPair] = useState<PairRecord | null>(null);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Best-effort: prices are supplementary, so a failure leaves the last values
  // and the table renders "—" for any unpriced leg (no error surfaced).
  const refreshPrices = useCallback(async () => {
    try {
      const res = await getPairPrices();
      setPrices(res.prices ?? {});
    } catch {
      /* keep previous prices */
    }
  }, []);

  // After a scan / data-source switch the live indexer can briefly rate-limit
  // the price fetch, leaving an all-"—" column; retry a few times with short
  // backoff so a transient miss self-heals in seconds, not at the 20s poll (#50).
  const refreshPricesRetrying = useCallback(async () => {
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const res = await getPairPrices();
        const next = res.prices ?? {};
        setPrices(next);
        if (Object.keys(next).length > 0) return;
      } catch {
        /* ignore and retry */
      }
      if (attempt < 3) await new Promise((r) => setTimeout(r, 2500));
    }
  }, []);

  const refreshPairs = useCallback(async () => {
    const res = await getPairs();
    setPairs(res.pairs);
    setScannedAt(res.scanned_at);
    // Surface a DB read failure rather than showing a misleading empty table.
    setError(res.error ?? null);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await getScanStatus();
        setStatus(s);
        if (!s.running) {
          stopPolling();
          await refreshPairs();
          await refreshPricesRetrying();
        }
      } catch {
        stopPolling();
      }
    }, POLL_MS);
  }, [refreshPairs, refreshPricesRetrying, stopPolling]);

  // Initial load: pairs + whether a scan is already running.
  useEffect(() => {
    (async () => {
      try {
        await refreshPairs();
        await refreshPrices();
        const s = await getScanStatus();
        setStatus(s);
        if (s.running) startPolling();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return stopPolling;
  }, [refreshPairs, refreshPrices, startPolling, stopPolling]);

  // Slow, independent price refresh while the table has rows.
  useEffect(() => {
    const id = setInterval(refreshPrices, PRICE_POLL_MS);
    return () => clearInterval(id);
  }, [refreshPrices]);

  // A data-source switch cleared the pairs server-side → reload (reloadKey>0
  // only; the initial mount is handled by the load effect above).
  useEffect(() => {
    if (reloadKey > 0) {
      refreshPairs();
      refreshPricesRetrying();
    }
  }, [reloadKey, refreshPairs, refreshPricesRetrying]);

  async function runScan(quick: boolean) {
    setError(null);
    try {
      await startScan(quick);
      setStatus((s) => (s ? { ...s, running: true, phase: 1 } : s));
      startPolling();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed to start");
    }
  }

  async function haltScan() {
    setError(null);
    try {
      // Reflect "Stopping…" immediately; the poll then settles to the stopped
      // run and refreshes the table with the partial survivors (issue #59).
      const s = await stopScan();
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop scan");
    }
  }

  const visiblePairs = filterByQuality(
    pairs,
    parseFloat(maxPvalue),
    parseFloat(maxHalfLife),
  );
  // A filter is "active" (narrowing) only when it actually hides pairs — used to
  // pick the right empty state and show the "showing X of Y" hint.
  const filterNarrowing = pairs.length > 0 && visiblePairs.length < pairs.length;

  const running = status?.running ?? false;
  const stopping = (status?.stop_requested ?? false) && running;
  const pct =
    status && status.total_pairs > 0
      ? Math.round((status.pairs_tested / status.total_pairs) * 100)
      : status && status.phase === 2 && status.total_markets > 0
        ? Math.round((status.markets_fetched / status.total_markets) * 100)
        : 0;

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-xs uppercase tracking-wider text-muted">
          Cointegrated Pairs
          <span className="ml-2 rounded-full bg-blue/20 px-1.5 py-0.5 text-xs text-blue">
            {pairs.length}
          </span>
        </h2>

        <div className="ml-auto flex flex-wrap items-center gap-4">
          <ZThresholdSlider value={threshold} onChange={setThreshold} />
          <button
            onClick={() => runScan(true)}
            disabled={running}
            data-testid="scan-quick"
            className="rounded border border-border px-2.5 py-1 text-xs text-muted transition hover:border-blue/60 hover:text-text disabled:opacity-40"
          >
            Quick scan
          </button>
          <button
            onClick={() => runScan(false)}
            disabled={running}
            data-testid="scan-full"
            className="rounded border border-blue px-2.5 py-1 text-xs text-blue transition hover:bg-blue/10 disabled:opacity-40"
          >
            {running ? "Scanning…" : "Full scan"}
          </button>
          {running && (
            <button
              onClick={haltScan}
              disabled={stopping}
              data-testid="scan-stop"
              title="Stop the scan now — keeps whatever pairs were found so far."
              className="rounded border border-red px-2.5 py-1 text-xs text-red transition hover:bg-red/10 disabled:opacity-40"
            >
              {stopping ? "Stopping…" : "Stop scan"}
            </button>
          )}
        </div>
      </div>

      {/* Scan-time triage controls (#150): narrow the table by cointegration
          strength / reversion speed and seed the Record popup's entry filter.
          Advisory only — entry re-validates on fresh data (#147). */}
      <div
        className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs"
        data-testid="triage-controls"
      >
        <span className="uppercase tracking-wider text-muted">
          Filter
          <InfoTip text="Scan-time triage: narrows the pairs below using each pair's p-value / half-life from the last scan, and pre-fills the Record popup with these values. Selection aid only — a recorded entry is still re-validated on fresh data and blocked if the pair has decayed." />
        </span>
        <label className="flex items-center gap-1.5">
          <span className="text-muted">max p-value</span>
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={maxPvalue}
            onChange={(e) => setMaxPvalue(e.target.value)}
            data-testid="triage-pvalue"
            className="w-20 rounded border border-border bg-bg px-2 py-1 text-text focus:border-blue focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-muted">max half-life (h)</span>
          <input
            type="number"
            step="1"
            min="0"
            value={maxHalfLife}
            onChange={(e) => setMaxHalfLife(e.target.value)}
            data-testid="triage-halflife"
            className="w-20 rounded border border-border bg-bg px-2 py-1 text-text focus:border-blue focus:outline-none"
          />
        </label>
        <button
          onClick={() => {
            setMaxPvalue(DEFAULT_PVALUE_MAX);
            setMaxHalfLife(DEFAULT_MAX_HALF_LIFE);
          }}
          data-testid="triage-reset"
          className="text-muted underline-offset-2 hover:text-text hover:underline"
        >
          reset
        </button>
        {filterNarrowing && (
          <span className="text-muted/70" data-testid="triage-count">
            showing {visiblePairs.length} of {pairs.length}
          </span>
        )}
      </div>

      {/* Progress / status line */}
      {running && (
        <div className="mb-4" data-testid="scan-progress">
          <div className="mb-1 flex justify-between text-xs text-muted">
            <span>{status?.progress_msg || "Working…"}</span>
            <span className="tabular-nums">{pct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg">
            <div
              className="h-full bg-blue transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {!running && status?.error && (
        <p className="mb-3 text-sm text-red">Scan error: {status.error}</p>
      )}
      {error && <p className="mb-3 text-sm text-red">{error}</p>}
      {!running && scannedAt && (
        <p className="mb-3 text-xs text-muted">
          Last scan: {new Date(scannedAt).toLocaleString()}
        </p>
      )}

      <PairsTable
        pairs={visiblePairs}
        threshold={threshold}
        prices={prices}
        onRecord={(p) => setRecordPair(p)}
        filterActive={filterNarrowing}
      />

      {recordPair && (
        <RecordManualTradeModal
          pair={recordPair}
          seedPvalueMax={maxPvalue}
          seedMaxHalfLife={maxHalfLife}
          onClose={() => setRecordPair(null)}
          onRecorded={() => onManualRecorded?.()}
        />
      )}
    </div>
  );
}
