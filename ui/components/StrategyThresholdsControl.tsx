"use client";

// Strategy-thresholds settings control (issue #74). Edits the Option-B entry /
// exit / stop Z thresholds app-wide at runtime; the pair-detail Z chart's
// reference lines + markers and the live/sim strategy defaults read them at call
// time, and the backend persists them (BotConfigHistory) so they survive a
// restart. Distinct from the dashboard's "Active when |Z|" slider, which stays a
// client-only filter over which pairs are recordable.

import { useEffect, useState } from "react";
import { getThresholds, setThresholds, type SignalThresholds } from "@/lib/api";

const DEFAULTS: SignalThresholds = { entry: 1.5, exit: 0.5, stop: 4.0 };

/** Drop trailing zeros so 4.0 reads as "4" (matches the Z-panel legend). */
function fmt(v: number): string {
  return Number(v.toFixed(2)).toString();
}

export default function StrategyThresholdsControl({
  onApplied,
}: {
  /** Notified with the applied values so a parent can refresh dependent views. */
  onApplied?: (t: SignalThresholds) => void;
}) {
  const [current, setCurrent] = useState<SignalThresholds | null>(null);
  const [draft, setDraft] = useState<SignalThresholds>(DEFAULTS);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getThresholds()
      .then((t) => {
        setCurrent(t);
        setDraft(t);
      })
      .catch(() => {
        /* leave the placeholder; the badge shows "…" until health resolves */
      });
  }, []);

  function startEdit() {
    if (current) setDraft(current);
    setErr(null);
    setEditing(true);
  }

  async function apply() {
    const { entry, exit, stop } = draft;
    if (!(exit < entry && entry < stop)) {
      setErr("Need exit < entry < stop");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await setThresholds(draft);
      const next = { entry: res.entry, exit: res.exit, stop: res.stop };
      setCurrent(next);
      setEditing(false);
      onApplied?.(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  if (!current) {
    return (
      <span
        data-testid="strategy-thresholds-badge"
        className="rounded-full bg-muted/20 px-2 py-0.5 text-xs font-medium text-muted"
      >
        …
      </span>
    );
  }

  return (
    <span
      className="flex items-center gap-1.5"
      data-testid="strategy-thresholds-control"
    >
      <span
        data-testid="strategy-thresholds-badge"
        title="The Option-B entry / exit / stop Z thresholds the chart and strategy use"
        className="rounded-full bg-blue/15 px-2 py-0.5 text-xs font-medium text-blue tabular-nums"
      >
        entry ±{fmt(current.entry)} · exit ±{fmt(current.exit)} · stop ±
        {fmt(current.stop)}
      </span>

      {editing ? (
        <span className="flex items-center gap-1">
          <Field
            label="exit"
            value={draft.exit}
            onChange={(v) => setDraft((d) => ({ ...d, exit: v }))}
            testid="threshold-exit"
          />
          <Field
            label="entry"
            value={draft.entry}
            onChange={(v) => setDraft((d) => ({ ...d, entry: v }))}
            testid="threshold-entry"
          />
          <Field
            label="stop"
            value={draft.stop}
            onChange={(v) => setDraft((d) => ({ ...d, stop: v }))}
            testid="threshold-stop"
          />
          <button
            onClick={apply}
            disabled={busy}
            data-testid="threshold-apply"
            className="rounded border border-blue px-1.5 py-0.5 text-blue hover:bg-blue/10 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Apply"}
          </button>
          <button
            onClick={() => {
              setEditing(false);
              setErr(null);
            }}
            className="rounded border border-border px-1.5 py-0.5 text-muted hover:text-text"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          onClick={startEdit}
          data-testid="threshold-edit"
          title="Edit the entry / exit / stop Z thresholds (applies app-wide)"
          className="rounded border border-border px-1.5 py-0.5 text-muted transition-colors hover:border-blue/60 hover:text-text"
        >
          Edit
        </button>
      )}
      {err && (
        <span className="text-red" data-testid="threshold-error">
          {err}
        </span>
      )}
    </span>
  );
}

function Field({
  label,
  value,
  onChange,
  testid,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  testid: string;
}) {
  return (
    <label className="flex items-center gap-0.5 text-muted">
      {label}
      <input
        type="number"
        step={0.1}
        value={value}
        aria-label={label}
        data-testid={testid}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-12 rounded border border-border bg-bg px-1 py-0.5 text-text tabular-nums"
      />
    </label>
  );
}
