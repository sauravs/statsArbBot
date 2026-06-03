"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createFFSim,
  getFFSim,
  listFFSims,
  stopFFSim,
  type FFSimulation,
} from "@/lib/api";
import CreateFFForm from "./CreateFFForm";
import FFSimList from "./FFSimList";
import FFSimDetail from "./FFSimDetail";

// Fast-forward simulation dashboard (PRD F7.3) — a create form + run list on the
// left, the selected run's detail (progress, equity curve, per-pair P&L, exit
// reasons) on the right. A RUNNING run is polled until it reaches a terminal state
// so the UI tracks progress without a manual refresh.
export default function FastForwardPanel() {
  const [sims, setSims] = useState<FFSimulation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FFSimulation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshList = useCallback(async () => {
    const res = await listFFSims();
    setSims(res.simulations);
    return res.simulations;
  }, []);

  useEffect(() => {
    refreshList().catch((e) =>
      setError(e instanceof Error ? e.message : "Failed to load simulations"),
    );
  }, [refreshList]);

  // Load + poll the selected run while it is RUNNING.
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      const run = await getFFSim(selectedId);
      if (cancelled) return;
      setDetail(run);
      if (run.status === "RUNNING" && !pollRef.current) {
        pollRef.current = setInterval(async () => {
          try {
            const next = await getFFSim(selectedId);
            if (cancelled) return;
            setDetail(next);
            if (next.status !== "RUNNING" && pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
              refreshList().catch(() => {});
            }
          } catch {
            /* transient poll error — keep the last known state */
          }
        }, 1000);
      }
    };
    load().catch((e) => {
      if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load run");
    });
    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [selectedId, refreshList]);

  const onStop = useCallback(async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await stopFFSim(detail.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stop failed");
    } finally {
      setBusy(false);
    }
  }, [detail]);

  return (
    <div className="space-y-6">
      {error && (
        <p className="text-sm text-red" data-testid="ff-error">
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <div className="space-y-6">
          <CreateFFForm
            onCreated={async (s) => {
              await refreshList();
              setSelectedId(s.id);
            }}
          />
          <FFSimList sims={sims} selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div>
          {detail ? (
            <FFSimDetail run={detail} busy={busy} onStop={onStop} />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-10">
              <p className="text-sm text-muted" data-testid="ff-no-selection">
                Select a run, or create one to begin.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
