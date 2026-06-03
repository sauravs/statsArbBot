"use client";

import { useState } from "react";
import { type LiveMode, type LiveSession } from "@/lib/api";
import Modal from "./Modal";

// Clamp the manual entry-Z override to the documented Z range (PRD F4.1, 0.5–4.0).
// `type=number` min/max only bound the spinner, not typed input, so an operator
// could otherwise send 0 (opens every pair) or an absurd value. Blank → undefined
// so the backend falls back to the Option-B config threshold (1.5).
function parseEntryZ(raw: string): number | undefined {
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n)) return undefined;
  return Math.min(4.0, Math.max(0.5, n));
}

// Live bot control surface (PRD F5.1/F5.5): mode tabs (forward_test / production),
// activate / deactivate, and the manual engine passes (entry scan, manage exits,
// abort-all). Passes are explicit POSTs this phase; APScheduler automation is
// Phase 6. Production is selectable but visibly flagged — it trades real money.
export default function BotControls({
  mode,
  onModeChange,
  session,
  busy,
  onActivate,
  onDeactivate,
  onEntryScan,
  onExitManage,
  onAbort,
}: {
  mode: LiveMode;
  onModeChange: (m: LiveMode) => void;
  session: LiveSession | null;
  busy: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
  onEntryScan: (entryThreshold?: number) => void;
  onExitManage: () => void;
  onAbort: () => void;
}) {
  const [entryZ, setEntryZ] = useState("1.5");
  const [confirmAbort, setConfirmAbort] = useState(false);
  const active = session?.active ?? false;

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="bot-controls">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-xs uppercase tracking-wider text-muted">Live Bot</h2>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            active ? "bg-green/20 text-green" : "bg-muted/20 text-muted"
          }`}
          data-testid="bot-status"
        >
          {active ? "ACTIVE" : "INACTIVE"}
        </span>

        {/* Mode tabs */}
        <div className="ml-auto flex overflow-hidden rounded-lg border border-border text-xs">
          {(["forward_test", "production"] as LiveMode[]).map((m) => (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              disabled={busy}
              data-testid={`mode-tab-${m}`}
              className={`px-3 py-1.5 transition disabled:opacity-40 ${
                mode === m
                  ? m === "production"
                    ? "bg-red/20 text-red"
                    : "bg-blue/20 text-blue"
                  : "text-muted hover:text-text"
              }`}
            >
              {m === "forward_test" ? "Forward test" : "Production"}
            </button>
          ))}
        </div>
      </div>

      {mode === "production" && (
        <p className="mb-3 text-xs text-yellow" data-testid="production-warning">
          ⚠ Production mode trades real funds on mainnet. Validate on testnet first.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {active ? (
          <button
            onClick={onDeactivate}
            disabled={busy}
            data-testid="deactivate-btn"
            className="rounded border border-border px-3 py-1.5 text-xs text-muted transition hover:border-red/60 hover:text-red disabled:opacity-40"
          >
            Deactivate
          </button>
        ) : (
          <button
            onClick={onActivate}
            disabled={busy}
            data-testid="activate-btn"
            className="rounded border border-green px-3 py-1.5 text-xs text-green transition hover:bg-green/10 disabled:opacity-40"
          >
            Activate
          </button>
        )}

        <span className="mx-1 h-5 w-px bg-border" />

        {/* Entry-Z override (defaults to the Option-B config threshold, 1.5). */}
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Entry Z
          <input
            type="number"
            step="0.1"
            min="0.5"
            max="4"
            value={entryZ}
            onChange={(e) => setEntryZ(e.target.value)}
            data-testid="entry-z-input"
            className="w-16 rounded border border-border bg-bg px-2 py-1 text-right tabular-nums text-text"
          />
        </label>
        <button
          onClick={() => onEntryScan(parseEntryZ(entryZ))}
          disabled={busy || !active}
          data-testid="entry-scan-btn"
          className="rounded border border-blue px-3 py-1.5 text-xs text-blue transition hover:bg-blue/10 disabled:opacity-40"
        >
          Run entry scan
        </button>
        <button
          onClick={onExitManage}
          disabled={busy}
          data-testid="exit-manage-btn"
          className="rounded border border-border px-3 py-1.5 text-xs text-muted transition hover:border-blue/60 hover:text-text disabled:opacity-40"
        >
          Manage exits
        </button>

        <span className="mx-1 h-5 w-px bg-border" />

        <button
          onClick={() => setConfirmAbort(true)}
          disabled={busy}
          data-testid="abort-btn"
          className="rounded border border-red px-3 py-1.5 text-xs text-red transition hover:bg-red/10 disabled:opacity-40"
        >
          Abort all
        </button>
      </div>

      {confirmAbort && (
        <Modal title="Abort all trades?" onClose={() => setConfirmAbort(false)} testid="abort-modal">
          <p className="mb-4 text-sm text-muted">
            This cancels all open orders and closes every position reduce-only,
            marking open trades as ABORTED. This cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setConfirmAbort(false)}
              className="rounded border border-border px-3 py-1.5 text-xs text-muted hover:text-text"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                setConfirmAbort(false);
                onAbort();
              }}
              data-testid="abort-confirm"
              className="rounded border border-red bg-red/10 px-3 py-1.5 text-xs text-red hover:bg-red/20"
            >
              Abort all
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
