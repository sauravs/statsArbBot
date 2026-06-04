"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getPairs,
  getPairPrices,
  getScanStatus,
  startScan,
  type PairRecord,
  type ScanStatus,
} from "@/lib/api";
import PairsTable from "./PairsTable";
import ZThresholdSlider from "./ZThresholdSlider";
import RecordManualTradeModal from "./RecordManualTradeModal";

const POLL_MS = 2000;
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
          await refreshPrices();
        }
      } catch {
        stopPolling();
      }
    }, POLL_MS);
  }, [refreshPairs, refreshPrices, stopPolling]);

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
      refreshPrices();
    }
  }, [reloadKey, refreshPairs, refreshPrices]);

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

  const running = status?.running ?? false;
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
        </div>
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
        pairs={pairs}
        threshold={threshold}
        prices={prices}
        onRecord={(p) => setRecordPair(p)}
      />

      {recordPair && (
        <RecordManualTradeModal
          pair={recordPair}
          onClose={() => setRecordPair(null)}
          onRecorded={() => onManualRecorded?.()}
        />
      )}
    </div>
  );
}
