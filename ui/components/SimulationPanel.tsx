"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSimSession,
  listSimSessions,
  pauseSim,
  resumeSim,
  stopSim,
  tickSim,
  topupSim,
  type SimOverview,
  type SimSession,
} from "@/lib/api";
import CreateSimForm from "./CreateSimForm";
import SimSessionList from "./SimSessionList";
import SimSessionDetail from "./SimSessionDetail";

// Real-time simulation dashboard (PRD F6.5) — a create form + session list on the
// left, the selected session's detail (metrics, controls, positions, trades) on
// the right. Every control runs one engine action then refreshes both the list and
// the open detail, so the UI mirrors the DB-backed engine state.
export default function SimulationPanel() {
  const [sessions, setSessions] = useState<SimSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [overview, setOverview] = useState<SimOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    const res = await listSimSessions();
    setSessions(res.sessions);
    return res.sessions;
  }, []);

  const refreshDetail = useCallback(async (id: string, isActive: () => boolean = () => true) => {
    const ov = await getSimSession(id);
    if (!isActive()) return;
    setOverview(ov);
  }, []);

  // Initial load.
  useEffect(() => {
    refreshList().catch((e) =>
      setError(e instanceof Error ? e.message : "Failed to load simulations"),
    );
  }, [refreshList]);

  // Load the detail whenever the selection changes (guarded against stale loads).
  useEffect(() => {
    if (!selectedId) {
      setOverview(null);
      return;
    }
    let cancelled = false;
    refreshDetail(selectedId, () => !cancelled).catch((e) => {
      if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load session");
    });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshDetail]);

  const run = useCallback(
    async (label: string, action: () => Promise<string | null>) => {
      // Capture the selection at click time; the post-action refresh re-checks it
      // so a mid-flight switch to another session can't overwrite its detail with
      // this one's (the action and its refresh have independent error slots, so a
      // transient refresh blip after a successful action reads as "view stale",
      // not "action failed" — mirrors LiveTradingPanel's Phase-5b fix).
      const sessionAtClick = selectedId;
      setBusy(true);
      setError(null);
      setMessage(null);
      setStale(null);
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
        await refreshList();
        if (sessionAtClick && sessionAtClick === selectedId) {
          await refreshDetail(sessionAtClick);
        }
      } catch (e) {
        setStale(
          e instanceof Error
            ? `View refresh failed (${e.message}) — data may be stale.`
            : "View refresh failed — data may be stale.",
        );
      } finally {
        setBusy(false);
      }
    },
    [refreshList, refreshDetail, selectedId],
  );

  return (
    <div className="space-y-6">
      {message && (
        <p className="text-sm text-muted" data-testid="sim-message">
          {message}
        </p>
      )}
      {error && (
        <p className="text-sm text-red" data-testid="sim-error">
          {error}
        </p>
      )}
      {stale && (
        <p className="text-sm text-yellow" data-testid="sim-stale">
          {stale}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <div className="space-y-6">
          <CreateSimForm
            onCreated={async (s) => {
              await refreshList();
              setSelectedId(s.id);
              setMessage(`Simulation "${s.label || s.id.slice(0, 6)}" created.`);
            }}
          />
          <SimSessionList
            sessions={sessions}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>

        <div>
          {overview ? (
            <SimSessionDetail
              overview={overview}
              busy={busy}
              onTick={() =>
                run("Tick", async () => {
                  const r = await tickSim(overview.session.id);
                  if (r.skipped) return `Tick skipped (${r.reason}).`;
                  return `Tick complete — ${r.entries ?? 0} opened, ${r.exits ?? 0} closed.`;
                })
              }
              onPause={() => run("Pause", async () => {
                await pauseSim(overview.session.id);
                return "Simulation paused.";
              })}
              onResume={() => run("Resume", async () => {
                await resumeSim(overview.session.id);
                return "Simulation resumed.";
              })}
              onStop={() => run("Stop", async () => {
                const r = await stopSim(overview.session.id);
                return `Simulation stopped — ${r.positions_closed} position(s) closed.`;
              })}
              onTopUp={(amount) => run("Top up", async () => {
                await topupSim(overview.session.id, amount);
                return `Topped up $${amount.toLocaleString()}.`;
              })}
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-10">
              <p className="text-sm text-muted" data-testid="sim-no-selection">
                Select a simulation, or create one to begin.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
