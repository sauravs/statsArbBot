"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  deleteStrategy,
  getStrategy,
  listSimSessions,
  listStrategies,
  listStrategySignificance,
  pauseStrategy,
  runStrategy,
  seedDefaultStrategies,
  stopStrategy,
  type Strategy,
} from "@/lib/api";
import { liveSimByStrategy, presetFromStrategy, stashSimPreset } from "@/lib/simPresets";
import CreateStrategyForm from "./CreateStrategyForm";
import StrategyList from "./StrategyList";
import StrategyDetail from "./StrategyDetail";

// Walk-forward backtest dashboard (PRD F8.4): a create form + ranked strategy
// comparison on the left, the selected strategy's detail (controls, equity curve,
// per-window table, per-pair P&L, report) on the right. A RUNNING sweep is polled
// until terminal so progress + final results appear without a manual refresh.
export default function BacktestPanel({ reloadKey = 0 }: { reloadKey?: number }) {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Strategy | null>(null);
  const [busy, setBusy] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // strategy id → the sim session paper-trading it, so the list can highlight
  // which saved strategy is the one currently live in simulation (Phase 5).
  const [liveSims, setLiveSims] = useState<
    Map<string, { status: string; label: string | null }>
  >(new Map());
  const router = useRouter();

  // Run / pause / stop are separate actions from create (unlike the FF replay,
  // which launches on create), so polling keys off the live RUNNING status rather
  // than the selection alone — flipping to RUNNING via the Run button re-arms it.
  // Also require the loaded detail to match the current selection, so a stale
  // RUNNING detail from a previous selection can't fire a poll against the new id.
  const isRunning = detail?.status === "RUNNING" && detail?.id === selectedId;

  const refreshList = useCallback(async () => {
    const res = await listStrategies();
    // Merge the leaderboard DSR (gate B3) onto each row for the significance badge.
    // Best-effort: a significance failure must not blank the list, so fall back to
    // the rows without a DSR (the badge simply doesn't render).
    const sig = await listStrategySignificance().catch(() => null);
    const rows = sig
      ? res.strategies.map((s) => ({ ...s, dsr: sig.dsr[s.id] ?? null }))
      : res.strategies;
    setStrategies(rows);
    // Which strategy is live in simulation right now. Best-effort for the same
    // reason as the DSR merge: a sim-list failure must not blank the strategy list,
    // it just means the highlight doesn't render.
    const sims = await listSimSessions().catch(() => null);
    setLiveSims(sims ? liveSimByStrategy(sims.sessions) : new Map());
    return rows;
  }, []);

  useEffect(() => {
    refreshList().catch((e) =>
      setError(e instanceof Error ? e.message : "Failed to load strategies"),
    );
  }, [refreshList]);

  // When the market-data source toggles (reloadKey bumps), the visible strategies
  // change (they're scoped to demo/live, issue #98) — drop the now-irrelevant
  // selection and reload the scoped list.
  useEffect(() => {
    if (reloadKey === 0) return; // initial mount already loads via the effect above
    setSelectedId(null);
    setDetail(null);
    refreshList().catch(() => {});
  }, [reloadKey, refreshList]);

  // Load the selected strategy when the selection changes.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    getStrategy(selectedId)
      .then((row) => {
        if (!cancelled) setDetail(row);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load strategy");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // Poll the selected strategy while its sweep is RUNNING; stop on a terminal state.
  useEffect(() => {
    if (!selectedId || !isRunning) return;
    let cancelled = false;
    let finalTimer: ReturnType<typeof setTimeout> | undefined;
    const timer = setInterval(async () => {
      try {
        const next = await getStrategy(selectedId);
        if (cancelled) return;
        setDetail(next);
        if (next.status !== "RUNNING") {
          clearInterval(timer);
          refreshList().catch(() => {});
          // The engine flips the status to a terminal state and only THEN recomputes
          // cross-strategy ranks (backtest/engine.py), so the row we just observed can
          // still carry the pre-run rank (often null). Polling has stopped, so without
          // this the detail would show no rank until a manual reselect. Re-fetch once,
          // shortly after, to land the freshly assigned rank + final fields.
          finalTimer = setTimeout(() => {
            getStrategy(selectedId)
              .then((finalRow) => {
                if (!cancelled) setDetail(finalRow);
              })
              .catch(() => {});
          }, 800);
        }
      } catch {
        /* transient poll error — keep the last known state */
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
      if (finalTimer) clearTimeout(finalTimer);
    };
  }, [selectedId, isRunning, refreshList]);

  // Run adopts the endpoint's returned RUNNING row as optimistic state: the
  // background sweep persists RUNNING a moment later, so setting it here re-arms the
  // RUNNING-keyed poll immediately — without it a re-fetch could read a not-yet-
  // updated PENDING row and never start polling.
  const onRun = useCallback(() => {
    if (!detail) return;
    const id = detail.id;
    setBusy(true);
    setError(null);
    runStrategy(id)
      .then((row) => {
        setDetail(row);
        return refreshList();
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Run failed"))
      .finally(() => setBusy(false));
  }, [detail, refreshList]);

  // Pause / stop only set an in-process flag the sweep honours at the next window
  // boundary; the endpoint returns the still-RUNNING row. Deliberately do NOT adopt
  // that row — the active poll observes the PAUSED/STOPPED transition, so adopting it
  // would flicker the controls back to RUNNING for a tick.
  const control = useCallback(
    (fn: () => Promise<Strategy>) => {
      setBusy(true);
      setError(null);
      fn()
        .then(() => refreshList())
        .catch((e) => setError(e instanceof Error ? e.message : "Action failed"))
        .finally(() => setBusy(false));
    },
    [refreshList],
  );

  const onPause = useCallback(() => {
    if (detail) control(() => pauseStrategy(detail.id));
  }, [detail, control]);
  const onStop = useCallback(() => {
    if (detail) control(() => stopStrategy(detail.id));
  }, [detail, control]);
  const onDelete = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await deleteStrategy(detail.id);
      setSelectedId(null);
      setDetail(null);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }, [detail, refreshList]);

  const onSeed = useCallback(async () => {
    setSeeding(true);
    setError(null);
    try {
      await seedDefaultStrategies();
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Seed failed");
    } finally {
      setSeeding(false);
    }
  }, [refreshList]);

  return (
    <div className="space-y-6">
      {error && (
        <p className="text-sm text-red" data-testid="bt-error">
          {error}
        </p>
      )}

      {/* 26rem, not 22rem: the grouped list carries safety badges and per-family
          statistics that a 22rem column truncates into uselessness. */}
      <div className="grid gap-6 lg:grid-cols-[26rem_1fr]">
        <div className="space-y-6">
          <CreateStrategyForm
            onCreated={async (s) => {
              await refreshList();
              setSelectedId(s.id);
            }}
          />
          <StrategyList
            strategies={strategies}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onSeed={onSeed}
            seeding={seeding}
            liveSimByStrategyId={liveSims}
          />
        </div>

        <div>
          {detail ? (
            <StrategyDetail
              onPaperTrade={(s) => {
                stashSimPreset(presetFromStrategy(s));
                router.push("/dashboard/sim");
              }}
              strategy={detail}
              busy={busy}
              onRun={onRun}
              onPause={onPause}
              onStop={onStop}
              onDelete={onDelete}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-10">
              <p className="text-sm text-muted" data-testid="bt-no-selection">
                Select a strategy, or create one to begin.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
