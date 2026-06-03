"use client";

import { useState } from "react";
import { createStrategy, type Strategy } from "@/lib/api";

// Create a backtest strategy (PRD F8.4). A strategy is a parameter set — the
// walk-forward window lengths plus the entry Z-threshold / Z-window that S1–S4
// vary. Advanced cost knobs use sensible server defaults. The date range is
// optional (blank ⇒ full demo history offline).
export default function CreateStrategyForm({
  onCreated,
}: {
  onCreated: (s: Strategy) => void;
}) {
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("10000");
  const [entryZ, setEntryZ] = useState("1.5");
  const [scanDays, setScanDays] = useState("90");
  const [tradeDays, setTradeDays] = useState("30");
  const [zwindow, setZwindow] = useState("21");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const s = await createStrategy({
        name: name.trim() || "Untitled strategy",
        starting_capital: Number(capital),
        entry_threshold: Number(entryZ),
        scan_window_days: Number(scanDays),
        trade_window_days: Number(tradeDays),
        zscore_window: Number(zwindow),
        // Interpret the datetime-local wall-clock value as UTC (append "Z"), like
        // the fast-forward form, so the range matches the UTC-anchored history.
        start_time: start ? new Date(`${start}Z`).toISOString() : undefined,
        end_time: end ? new Date(`${end}Z`).toISOString() : undefined,
      });
      onCreated(s);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="create-strategy-form">
      <h2 className="mb-4 text-xs uppercase tracking-wider text-muted">New Strategy</h2>
      <div className="space-y-3">
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My strategy"
            className="bt-input"
            data-testid="strategy-name"
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
              className="bt-input"
              data-testid="strategy-capital"
            />
          </Field>
          <Field label="Entry |Z| ≥">
            <input
              type="number"
              min="0.5"
              max="4"
              step="0.1"
              value={entryZ}
              onChange={(e) => setEntryZ(e.target.value)}
              className="bt-input"
              data-testid="strategy-entry-z"
            />
          </Field>
          <Field label="Scan window (days)">
            <input
              type="number"
              min="1"
              step="1"
              value={scanDays}
              onChange={(e) => setScanDays(e.target.value)}
              className="bt-input"
              data-testid="strategy-scan-days"
            />
          </Field>
          <Field label="Trade window (days)">
            <input
              type="number"
              min="1"
              step="1"
              value={tradeDays}
              onChange={(e) => setTradeDays(e.target.value)}
              className="bt-input"
              data-testid="strategy-trade-days"
            />
          </Field>
          <Field label="Z-score window (bars)">
            <input
              type="number"
              min="3"
              step="1"
              value={zwindow}
              onChange={(e) => setZwindow(e.target.value)}
              className="bt-input"
              data-testid="strategy-zwindow"
            />
          </Field>
        </div>
        <Field label="Start (optional — full history if blank)">
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="bt-input"
            data-testid="strategy-start"
          />
        </Field>
        <Field label="End (optional)">
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="bt-input"
            data-testid="strategy-end"
          />
        </Field>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red" data-testid="create-strategy-error">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="mt-4 w-full rounded-lg bg-blue/20 px-3 py-2 text-sm font-medium text-blue transition-colors hover:bg-blue/30 disabled:opacity-50"
        data-testid="create-strategy-btn"
      >
        {busy ? "Creating…" : "Create strategy"}
      </button>

      <style jsx>{`
        :global(.bt-input) {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid #21262d;
          background: #0a0b0d;
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
          color: #e4e6ea;
        }
        :global(.bt-input:focus) {
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
