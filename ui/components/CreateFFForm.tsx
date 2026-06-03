"use client";

import { useState } from "react";
import { createFFSim, type FFSimulation } from "@/lib/api";

// Create a fast-forward replay (PRD F7.3). Collects the paper-account capital, the
// entry threshold, and an optional date range (omit it offline to replay the full
// demo history). Advanced cost knobs use sensible defaults server-side.
export default function CreateFFForm({
  onCreated,
}: {
  onCreated: (s: FFSimulation) => void;
}) {
  const [label, setLabel] = useState("");
  const [capital, setCapital] = useState("10000");
  const [entryZ, setEntryZ] = useState("1.5");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const sim = await createFFSim({
        label: label.trim() || undefined,
        starting_capital: Number(capital),
        entry_threshold: Number(entryZ),
        start_time: start ? new Date(start).toISOString() : undefined,
        end_time: end ? new Date(end).toISOString() : undefined,
      });
      onCreated(sim);
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="create-ff-form">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">New Replay</h2>
      <div className="space-y-3">
        <Field label="Label (optional)">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="My replay"
            className="ff-input"
            data-testid="ff-label"
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
              className="ff-input"
              data-testid="ff-capital"
            />
          </Field>
          <Field label="Entry |Z| threshold">
            <input
              type="number"
              min="0.5"
              max="4"
              step="0.1"
              value={entryZ}
              onChange={(e) => setEntryZ(e.target.value)}
              className="ff-input"
              data-testid="ff-entry-z"
            />
          </Field>
        </div>
        <Field label="Start (optional — full history if blank)">
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="ff-input"
            data-testid="ff-start"
          />
        </Field>
        <Field label="End (optional)">
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="ff-input"
            data-testid="ff-end"
          />
        </Field>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red" data-testid="create-ff-error">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-4 w-full rounded-lg bg-blue/20 px-3 py-2 text-sm font-medium text-blue transition-colors hover:bg-blue/30 disabled:opacity-50"
        data-testid="create-ff-btn"
      >
        {busy ? "Starting…" : "Run replay"}
      </button>

      <style jsx>{`
        :global(.ff-input) {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          background: #0a0b0d;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          color: #e4e6ea;
        }
        :global(.ff-input:focus) {
          outline: none;
          border-color: rgba(74, 144, 226, 0.6);
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}
