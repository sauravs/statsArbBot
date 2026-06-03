"use client";

import { useCallback, useEffect, useState } from "react";
import {
  abortLive,
  getLiveAccount,
  getLiveSession,
  getLiveTrades,
  runEntryScan,
  runExitManage,
  startLiveSession,
  stopLiveSession,
  type LiveAccount,
  type LiveMode,
  type LiveSession,
  type LiveTrade,
} from "@/lib/api";
import BotControls from "./BotControls";
import AccountCard from "./AccountCard";
import PortfolioStatus from "./PortfolioStatus";
import OpenTradesTable from "./OpenTradesTable";
import TradeHistoryPanel from "./TradeHistoryPanel";

// Live Trading dashboard (PRD F5.5) — composes the bot controls with the account,
// portfolio, open trades, and history, all keyed off the selected mode. Every
// control runs one engine pass then refreshes, so the UI mirrors engine state.
export default function LiveTradingPanel() {
  const [mode, setMode] = useState<LiveMode>("forward_test");
  const [session, setSession] = useState<LiveSession | null>(null);
  const [account, setAccount] = useState<LiveAccount | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [trades, setTrades] = useState<LiveTrade[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  // `isActive` gates the setStates so a stale in-flight refresh (e.g. the prior
  // mode's, still resolving after a fast mode-tab switch) can't overwrite the
  // current mode's state. Defaults to always-apply for the post-action path,
  // where the tabs are locked (busy) and no overlap is possible.
  const refresh = useCallback(
    async (m: LiveMode, isActive: () => boolean = () => true) => {
      // Session + trades come from the DB (always available). The account reads
      // the exchange and may fail independently, so it has its own error slot.
      const [sessionRes, tradesRes] = await Promise.all([
        getLiveSession(m),
        getLiveTrades(m),
      ]);
      if (!isActive()) return;
      setSession(sessionRes.session);
      setTrades(tradesRes.trades);
      try {
        const acc = await getLiveAccount(m);
        if (!isActive()) return;
        setAccount(acc);
        setAccountError(null);
      } catch (e) {
        if (!isActive()) return;
        setAccount(null);
        setAccountError(e instanceof Error ? e.message : "Account unavailable");
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    setMessage(null);
    setError(null);
    setRefreshError(null);
    refresh(mode, () => !cancelled).catch((e) => {
      if (!cancelled)
        setError(e instanceof Error ? e.message : "Failed to load live state");
    });
    return () => {
      cancelled = true;
    };
  }, [mode, refresh]);

  // Run an action, surface its result message, then refresh. The action and the
  // refresh have independent error slots: a successful action followed by a
  // transient refresh blip must NOT read as an action failure (it surfaces as a
  // separate "view may be stale" warning instead).
  const run = useCallback(
    async (label: string, action: () => Promise<string | null>) => {
      setBusy(true);
      setError(null);
      setRefreshError(null);
      let actionMsg: string | null = null;
      try {
        actionMsg = await action();
      } catch (e) {
        setError(e instanceof Error ? e.message : `${label} failed`);
        setBusy(false);
        return;
      }
      setMessage(actionMsg ?? `${label} complete.`);
      try {
        await refresh(mode);
      } catch (e) {
        setRefreshError(
          e instanceof Error
            ? `View refresh failed (${e.message}) — data may be stale.`
            : "View refresh failed — data may be stale.",
        );
      } finally {
        setBusy(false);
      }
    },
    [mode, refresh],
  );

  return (
    <div className="space-y-6">
      <BotControls
        mode={mode}
        onModeChange={setMode}
        session={session}
        busy={busy}
        onActivate={() =>
          run("Activate", async () => {
            await startLiveSession(mode);
            return "Bot activated.";
          })
        }
        onDeactivate={() =>
          run("Deactivate", async () => {
            const r = await stopLiveSession(mode);
            return `Bot deactivated (${r.stopped_sessions} session(s)).`;
          })
        }
        onEntryScan={(entryZ) =>
          run("Entry scan", async () => {
            const r = await runEntryScan(mode, entryZ);
            return r.message;
          })
        }
        onExitManage={() =>
          run("Exit management", async () => {
            const r = await runExitManage(mode);
            return r.message;
          })
        }
        onAbort={() =>
          run("Abort", async () => {
            const r = await abortLive(mode);
            // `positions_closed` has one entry per *attempt*; `ok=false` means the
            // reduce-only close failed and the position may still be LIVE (the
            // engine raises CODE-RED server-side). Count only successes, and route
            // any failure to the red error slot — never a green "success" that
            // contradicts a still-open exchange position.
            const ok = r.positions_closed.filter((p) => p.ok).length;
            const failed = r.positions_closed.filter((p) => !p.ok);
            if (failed.length) {
              throw new Error(
                `Abort INCOMPLETE — ${failed.length} position(s) may still be LIVE on the exchange: ${failed
                  .map((f) => f.market)
                  .join(", ")}. Check the exchange immediately.`,
              );
            }
            return `Abort complete — ${r.trades_marked} trade(s) marked, ${ok} position(s) closed.`;
          })
        }
      />

      {message && (
        <p className="text-sm text-muted" data-testid="action-message">
          {message}
        </p>
      )}
      {error && (
        <p className="text-sm text-red" data-testid="action-error">
          {error}
        </p>
      )}
      {refreshError && (
        <p className="text-sm text-yellow" data-testid="refresh-error">
          {refreshError}
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <AccountCard account={account} error={accountError} />
        <PortfolioStatus trades={trades} />
      </div>

      <OpenTradesTable trades={trades} />
      <TradeHistoryPanel trades={trades} />
    </div>
  );
}
