"use client";

import { useState } from "react";
import { createSimSession, type SimSession } from "@/lib/api";

// Create a real-time simulation session (PRD F6.5). Collects the paper-account
// capital, tick interval, and entry threshold; advanced cost knobs use sensible
// defaults server-side. On success the new session is handed back to the panel.
export default function CreateSimForm({
  onCreated,
}: {
  onCreated: (s: SimSession) => void;
}) {
  const [label, setLabel] = useState("");
  const [capital, setCapital] = useState("10000");
  const [interval, setInterval] = useState("60");
  const [entryZ, setEntryZ] = useState("1.5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const session = await createSimSession({
        label: label.trim() || undefined,
        starting_capital: Number(capital),
        interval_seconds: Number(interval),
        entry_threshold: Number(entryZ),
      });
      onCreated(session);
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="rounded-xl border border-border bg-card p-5"
      data-testid="create-sim-form"
    >
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">
        New Simulation
      </h2>
      <div className="space-y-3">
        <Field label="Label (optional)">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="My paper run"
            className="input"
            data-testid="sim-label"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starting capital ($)">
            <input
              type="number"
              min="1"
              step="100"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
              className="input"
              data-testid="sim-capital"
            />
          </Field>
          <Field label="Tick interval (s)">
            <input
              type="number"
              min="1"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="input"
              data-testid="sim-interval"
            />
          </Field>
        </div>
        <Field label="Entry |Z| threshold">
          <input
            type="number"
            min="0.5"
            max="4"
            step="0.1"
            value={entryZ}
            onChange={(e) => setEntryZ(e.target.value)}
            className="input"
            data-testid="sim-entry-z"
          />
        </Field>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red" data-testid="create-sim-error">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-4 w-full rounded-lg bg-blue/20 px-3 py-2 text-sm font-medium text-blue transition-colors hover:bg-blue/30 disabled:opacity-50"
        data-testid="create-sim-btn"
      >
        {busy ? "Creating…" : "Create & start"}
      </button>

      <style jsx>{`
        :global(.input) {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          background: #0a0b0d;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          color: #e4e6ea;
        }
        :global(.input:focus) {
          outline: none;
          border-color: rgba(74, 144, 226, 0.6);
        }
      `}</style>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}
