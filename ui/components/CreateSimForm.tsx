"use client";

import { useState } from "react";
import { createSimSession, type CreateSimInput, type SimSession } from "@/lib/api";
import { PHASE5_REHEARSAL } from "@/lib/simPresets";

// Create a real-time simulation session (PRD F6.5).
//
// This used to collect four fields (capital, interval, entry-Z, label) and leave
// everything else to server defaults — which meant the documented rehearsal
// parameterisation could not be expressed from the UI at all, even though the API
// has always accepted it. Phase 5 opens the full set, because the two knobs that
// decide whether a paper run means anything are exactly the ones that were hidden:
// **per-leg size** and **max concurrent pairs**.
export default function CreateSimForm({
  onCreated,
  initial,
}: {
  onCreated: (s: SimSession) => void;
  /** Prefill (e.g. launched from a saved strategy). */
  initial?: CreateSimInput;
}) {
  const [form, setForm] = useState<CreateSimInput>(initial ?? BLANK);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof CreateSimInput>(key: K, value: CreateSimInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // Blank ⇒ "don't apply this bound". Sent as null so the backend stores NULL
  // rather than coercing an empty string to 0, which would silently reject every pair.
  function optNum(v: string): number | null {
    const t = v.trim();
    return t === "" ? null : Number(t);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const session = await createSimSession({
        ...form,
        label: form.label?.trim() || undefined,
      });
      onCreated(session);
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
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted">New Simulation</h2>
        <button
          type="button"
          onClick={() => setForm({ ...PHASE5_REHEARSAL })}
          className="rounded border border-amber/40 bg-amber/10 px-2 py-0.5 text-[10px] font-medium text-amber transition-colors hover:bg-amber/20"
          data-testid="sim-preset-btn"
          title={
            "Load the Phase-5 rehearsal parameters (docs/PHASE5_PAPER_TRADING_PLAN.md §3.1).\n\n" +
            "entry |Z|≥4.0 · exit 0.5 · stop 5.0 · p≤0.01 · half-life ≤72h\n" +
            "$100/leg · max 5 concurrent pairs · 5-min ticks\n\n" +
            "This is the least-bad EXECUTABLE config, not a profitable one: +$0.248/trade " +
            "with 5 of 12 out-of-sample months negative — inside the ±$212 noise floor."
          }
        >
          Load Phase-5 preset
        </button>
      </div>

      <div className="space-y-3">
        <Field label="Label (optional)">
          <input
            value={form.label ?? ""}
            onChange={(e) => set("label", e.target.value)}
            placeholder="My paper run"
            className="input"
            data-testid="sim-label"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Starting capital ($)">
            <input
              type="number" min="1" step="100"
              value={form.starting_capital}
              onChange={(e) => set("starting_capital", Number(e.target.value))}
              className="input"
              data-testid="sim-capital"
            />
          </Field>
          <Field label="Tick interval (s)">
            <input
              type="number" min="1"
              value={form.interval_seconds}
              onChange={(e) => set("interval_seconds", Number(e.target.value))}
              className="input"
              data-testid="sim-interval"
            />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Entry |Z|">
            <input
              type="number" min="0.5" max="4" step="0.05"
              value={form.entry_threshold ?? ""}
              onChange={(e) => set("entry_threshold", Number(e.target.value))}
              className="input"
              data-testid="sim-entry-z"
            />
          </Field>
          <Field label="Exit |Z|">
            <input
              type="number" min="0.01" max="2" step="0.05"
              value={form.exit_threshold ?? ""}
              onChange={(e) => set("exit_threshold", Number(e.target.value))}
              className="input"
              data-testid="sim-exit-z"
            />
          </Field>
          <Field label="Stop |Z|">
            <input
              type="number" min="1" max="10" step="0.25"
              value={form.stop_threshold ?? ""}
              onChange={(e) => set("stop_threshold", Number(e.target.value))}
              className="input"
              data-testid="sim-stop-z"
            />
          </Field>
        </div>

        {/* The two fields that decide whether a paper run is executable by hand.
            Deliberately NOT behind "advanced" — hiding them is what made the old
            form unable to express the rehearsal at all. */}
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Capital per leg ($)"
            hint="Only $100/leg was measured at a workload a person can execute."
          >
            <input
              type="number" min="1" step="10"
              value={form.usd_per_trade ?? ""}
              onChange={(e) => set("usd_per_trade", Number(e.target.value))}
              className="input"
              data-testid="sim-usd-per-trade"
            />
          </Field>
          <Field
            label="Max concurrent pairs"
            hint="Blank = uncapped. Uncapped needs 20–100 open at once — not hand-executable."
          >
            <input
              type="number" min="1" max="100" step="1"
              value={form.max_active_pairs ?? ""}
              onChange={(e) => set("max_active_pairs", optNum(e.target.value))}
              className="input"
              data-testid="sim-max-active-pairs"
            />
          </Field>
        </div>

        <button
          type="button"
          onClick={() => setAdvanced((v) => !v)}
          className="text-[11px] text-muted underline decoration-dotted hover:text-text"
          data-testid="sim-advanced-toggle"
        >
          {advanced ? "Hide" : "Show"} advanced (pair quality &amp; costs)
        </button>

        {advanced && (
          <div className="space-y-3 rounded-lg border border-border/60 bg-bg/40 p-3">
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Max p-value"
                hint="Blank = whatever the scan allowed (0.05). Recommended 0.01."
              >
                <input
                  type="number" min="0.0001" max="1" step="0.005"
                  value={form.pvalue_max ?? ""}
                  onChange={(e) => set("pvalue_max", optNum(e.target.value))}
                  className="input"
                  data-testid="sim-pvalue-max"
                />
              </Field>
              <Field label="Max half-life (h)" hint="Blank = no cap. Measured non-binding.">
                <input
                  type="number" min="1" step="1"
                  value={form.max_half_life_h ?? ""}
                  onChange={(e) => set("max_half_life_h", optNum(e.target.value))}
                  className="input"
                  data-testid="sim-max-half-life"
                />
              </Field>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Z-window">
                <input
                  type="number" min="3" max="500" step="1"
                  value={form.zscore_window ?? ""}
                  onChange={(e) => set("zscore_window", Number(e.target.value))}
                  className="input"
                  data-testid="sim-zscore-window"
                />
              </Field>
              <Field label="Taker fee %">
                <input
                  type="number" min="0" max="5" step="0.005"
                  value={form.taker_fee_pct ?? ""}
                  onChange={(e) => set("taker_fee_pct", Number(e.target.value))}
                  className="input"
                  data-testid="sim-taker-fee"
                />
              </Field>
              <Field label="Slippage % (fallback)" hint="Overridden per market when the honest cost model is on.">
                <input
                  type="number" min="0" max="5" step="0.005"
                  value={form.slippage_pct ?? ""}
                  onChange={(e) => set("slippage_pct", Number(e.target.value))}
                  className="input"
                  data-testid="sim-slippage"
                />
              </Field>
            </div>
          </div>
        )}
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

const BLANK: CreateSimInput = {
  label: "",
  starting_capital: 10000,
  interval_seconds: 60,
  entry_threshold: 1.5,
  exit_threshold: 0.5,
  stop_threshold: 4.0,
  usd_per_trade: 100,
  max_active_pairs: null,
};

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block" title={hint}>
      <span className="mb-1 block text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}
