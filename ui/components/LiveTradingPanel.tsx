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

  const refresh = useCallback(async (m: LiveMode) => {
    // Session + trades come from the DB (always available). The account reads the
    // exchange and may fail independently, so it has its own error slot.
    const [sessionRes, tradesRes] = await Promise.all([
      getLiveSession(m),
      getLiveTrades(m),
    ]);
    setSession(sessionRes.session);
    setTrades(tradesRes.trades);
    try {
      setAccount(await getLiveAccount(m));
      setAccountError(null);
    } catch (e) {
      setAccount(null);
      setAccountError(e instanceof Error ? e.message : "Account unavailable");
    }
  }, []);

  useEffect(() => {
    setMessage(null);
    setError(null);
    refresh(mode).catch((e) =>
      setError(e instanceof Error ? e.message : "Failed to load live state"),
    );
  }, [mode, refresh]);

  // Run an action, surface its result message, then refresh — the shared wrapper
  // every control uses so the UI never drifts from engine state.
  const run = useCallback(
    async (label: string, action: () => Promise<string | null>) => {
      setBusy(true);
      setError(null);
      try {
        const msg = await action();
        setMessage(msg ?? `${label} complete.`);
        await refresh(mode);
      } catch (e) {
        setError(e instanceof Error ? e.message : `${label} failed`);
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
            return `Abort complete — ${r.trades_marked} trade(s) marked, ${r.positions_closed.length} position(s) closed.`;
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

      <div className="grid gap-6 md:grid-cols-2">
        <AccountCard account={account} error={accountError} />
        <PortfolioStatus trades={trades} />
      </div>

      <OpenTradesTable trades={trades} />
      <TradeHistoryPanel trades={trades} />
    </div>
  );
}
