"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createCampaign,
  listCampaigns,
  getCampaign,
  pauseCampaign,
  resumeCampaign,
  stopCampaign,
  deleteCampaign,
  type Campaign,
  type CampaignStatus,
  type Strategy,
} from "@/lib/api";
import InfoTip from "./InfoTip";

// Campaign launch + monitor panel (Phase-3 WS3, Slice 3). Compose a small grid
// spec (windows × an entry-Z axis), launch it, and watch the bounded-concurrency
// queue drive the members to DONE. The backend expands the grid, auto-starts the
// run, and stamps honest cost (per-market slippage + market impact) by default.
const POLL_MS = 3000;

const STATUS_STYLE: Record<CampaignStatus, string> = {
  PENDING: "bg-muted/20 text-muted",
  RUNNING: "bg-blue/20 text-blue",
  PAUSED: "bg-yellow/20 text-yellow",
  DONE: "bg-green/20 text-green",
  STOPPED: "bg-red/20 text-red",
};

// Member strategies carry a BacktestStatus (COMPLETED/FAILED/… — a different set).
const MEMBER_STATUS_STYLE: Record<string, string> = {
  PENDING: "bg-muted/20 text-muted",
  RUNNING: "bg-blue/20 text-blue",
  PAUSED: "bg-yellow/20 text-yellow",
  COMPLETED: "bg-green/20 text-green",
  STOPPED: "bg-red/20 text-red",
  FAILED: "bg-red/20 text-red",
};

function toUtcIso(local: string): string {
  // datetime-local is wall-clock; interpret as UTC (append Z), like the backtest form.
  return new Date(`${local}Z`).toISOString();
}

interface WindowRow {
  label: string;
  start: string;
  end: string;
}

export default function CampaignPanel() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [members, setMembers] = useState<Strategy[]>([]);
  const [error, setError] = useState<string | null>(null);

  // ── launch form ──
  const [name, setName] = useState("");
  const [concurrency, setConcurrency] = useState("2");
  const [entryZ, setEntryZ] = useState("1.0, 1.5");
  const [scanDays, setScanDays] = useState("7");
  const [tradeDays, setTradeDays] = useState("3");
  const [windows, setWindows] = useState<WindowRow[]>([
    { label: "w1", start: "", end: "" },
  ]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await listCampaigns();
      setCampaigns(res.campaigns);
    } catch {
      /* transient; keep the last list */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // Re-fetch the expanded campaign's members alongside the poll.
  useEffect(() => {
    if (!expanded) return;
    let alive = true;
    const load = async () => {
      try {
        const res = await getCampaign(expanded);
        if (alive) setMembers(res.strategies);
      } catch {
        /* keep last */
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [expanded, campaigns]);

  async function launch() {
    setError(null);
    const rows = windows.filter((w) => w.start && w.end);
    if (rows.length === 0) {
      setError("Add at least one window with a start and end.");
      return;
    }
    const entry = entryZ
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (entry.length === 0) {
      setError("Enter at least one entry-Z value.");
      return;
    }
    setBusy(true);
    try {
      await createCampaign({
        name: name.trim() || "Campaign",
        concurrency: Number(concurrency),
        windows: rows.map((w, i) => ({
          label: w.label.trim() || `w${i + 1}`,
          start: toUtcIso(w.start),
          end: toUtcIso(w.end),
        })),
        axes: { entry_threshold: entry },
        base: {
          scan_window_days: Number(scanDays),
          trade_window_days: Number(tradeDays),
        },
      });
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Launch failed");
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  return (
    <div className="mt-8 rounded-xl border border-border bg-card p-5" data-testid="campaign-panel">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-base font-bold">Campaigns</h2>
        <InfoTip text="Expand a parameter grid (windows × entry-Z) into many backtests and run them with bounded concurrency. Members are stamped phase-2 and run with honest cost (per-market slippage + market impact) on by default. Deleting a campaign detaches its runs, never deletes them." />
      </div>

      {/* ── Launch form ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3" data-testid="campaign-form">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Name
          <input
            data-testid="campaign-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="entry-sweep"
            className="bt-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Entry-Z values (comma-sep)
          <input
            data-testid="campaign-entry-z"
            value={entryZ}
            onChange={(e) => setEntryZ(e.target.value)}
            className="bt-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Concurrency
          <input
            type="number"
            min={1}
            max={8}
            data-testid="campaign-concurrency"
            value={concurrency}
            onChange={(e) => setConcurrency(e.target.value)}
            className="bt-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Scan window (days)
          <input
            type="number"
            min={1}
            data-testid="campaign-scan-days"
            value={scanDays}
            onChange={(e) => setScanDays(e.target.value)}
            className="bt-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Trade window (days)
          <input
            type="number"
            min={1}
            data-testid="campaign-trade-days"
            value={tradeDays}
            onChange={(e) => setTradeDays(e.target.value)}
            className="bt-input"
          />
        </label>
      </div>

      <div className="mt-3" data-testid="campaign-windows">
        <div className="mb-1 flex items-center gap-2 text-xs text-muted">
          Windows (OOS date spans)
          <button
            type="button"
            data-testid="campaign-add-window"
            onClick={() =>
              setWindows((w) => [...w, { label: `w${w.length + 1}`, start: "", end: "" }])
            }
            className="rounded border border-border px-1.5 py-0.5 text-[10px] hover:border-blue/60"
          >
            + window
          </button>
        </div>
        {windows.map((w, i) => (
          <div key={i} className="mb-1 flex flex-wrap items-center gap-2" data-testid="campaign-window-row">
            <input
              value={w.label}
              onChange={(e) =>
                setWindows((ws) => ws.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))
              }
              className="bt-input w-16"
              aria-label={`window ${i + 1} label`}
            />
            <input
              type="datetime-local"
              data-testid={`campaign-window-start-${i}`}
              value={w.start}
              onChange={(e) =>
                setWindows((ws) => ws.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))
              }
              className="bt-input"
              aria-label={`window ${i + 1} start`}
            />
            <input
              type="datetime-local"
              data-testid={`campaign-window-end-${i}`}
              value={w.end}
              onChange={(e) =>
                setWindows((ws) => ws.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))
              }
              className="bt-input"
              aria-label={`window ${i + 1} end`}
            />
            {windows.length > 1 && (
              <button
                type="button"
                onClick={() => setWindows((ws) => ws.filter((_, j) => j !== i))}
                className="text-xs text-red hover:underline"
                aria-label={`remove window ${i + 1}`}
              >
                ✕
              </button>
            )}
          </div>
        ))}
      </div>

      <button
        type="button"
        data-testid="campaign-launch"
        onClick={launch}
        disabled={busy}
        className="mt-3 rounded-lg bg-blue px-4 py-1.5 text-sm font-medium text-white hover:bg-blue/90 disabled:opacity-50"
      >
        {busy ? "Launching…" : "Launch campaign"}
      </button>
      {error && (
        <p className="mt-2 text-sm text-red" data-testid="campaign-error">
          {error}
        </p>
      )}

      {/* ── Monitor ── */}
      <div className="mt-6" data-testid="campaign-list">
        {campaigns.length === 0 ? (
          <p className="text-sm text-muted" data-testid="campaign-empty">
            No campaigns yet. Launch one above.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {campaigns.map((c) => (
              <li key={c.id} className="rounded-lg border border-border p-3" data-testid="campaign-row">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => setExpanded((e) => (e === c.id ? null : c.id))}
                    className="font-medium hover:underline"
                    data-testid="campaign-row-name"
                  >
                    {c.name}
                  </button>
                  <span
                    data-testid="campaign-row-status"
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[c.status]}`}
                  >
                    {c.status}
                  </span>
                  <span className="text-xs text-muted" data-testid="campaign-row-progress">
                    {c.completed}/{c.total} done{c.failed > 0 ? ` · ${c.failed} failed` : ""}
                  </span>
                  <span className="ml-auto flex items-center gap-1">
                    {c.status === "RUNNING" && (
                      <button data-testid="campaign-pause" onClick={() => act(() => pauseCampaign(c.id))} className="rounded border border-yellow px-2 py-0.5 text-xs text-yellow hover:bg-yellow/10">Pause</button>
                    )}
                    {c.status === "PAUSED" && (
                      <button data-testid="campaign-resume" onClick={() => act(() => resumeCampaign(c.id))} className="rounded border border-blue px-2 py-0.5 text-xs text-blue hover:bg-blue/10">Resume</button>
                    )}
                    {(c.status === "RUNNING" || c.status === "PAUSED") && (
                      <button data-testid="campaign-stop" onClick={() => act(() => stopCampaign(c.id))} className="rounded border border-red px-2 py-0.5 text-xs text-red hover:bg-red/10">Stop</button>
                    )}
                    <button data-testid="campaign-delete" onClick={() => act(() => deleteCampaign(c.id))} title="Delete the campaign (its runs are detached, not deleted)" className="rounded border border-border px-2 py-0.5 text-xs text-muted hover:border-red/60 hover:text-red">Delete</button>
                  </span>
                </div>

                {expanded === c.id && (
                  <ul className="mt-2 flex flex-col gap-1 border-t border-border pt-2" data-testid="campaign-members">
                    {members.map((m) => (
                      <li key={m.id} className="flex items-center gap-2 text-xs" data-testid="campaign-member-row">
                        <span className="truncate">{m.name}</span>
                        <span className={`ml-auto rounded-full px-1.5 py-0.5 ${MEMBER_STATUS_STYLE[m.status] ?? "bg-muted/20 text-muted"}`}>
                          {m.status}
                        </span>
                      </li>
                    ))}
                    {members.length === 0 && <li className="text-xs text-muted">No members.</li>}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
