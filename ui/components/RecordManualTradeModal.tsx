"use client";

import { useState } from "react";
import { recordManualTrade, type PairRecord } from "@/lib/api";
import Modal from "./Modal";

// Capital-allocation popup (PRD F4.4/F4.5): collect USD for each leg, then record.
export default function RecordManualTradeModal({
  pair,
  onClose,
  onRecorded,
}: {
  pair: PairRecord;
  onClose: () => void;
  onRecorded: () => void;
}) {
  const [leg1, setLeg1] = useState("100");
  const [leg2, setLeg2] = useState("100");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const c1 = parseFloat(leg1);
  const c2 = parseFloat(leg2);
  const valid = c1 > 0 && c2 > 0;

  async function submit() {
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await recordManualTrade({
        base_market: pair.base_market,
        quote_market: pair.quote_market,
        capital_leg1_usd: c1,
        capital_leg2_usd: c2,
      });
      onRecorded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record trade");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Record manual trade — ${pair.base_market} / ${pair.quote_market}`}
      onClose={onClose}
      testid="record-modal"
    >
      <p className="mb-4 text-xs text-muted">
        Z {pair.z_score?.toFixed(3) ?? "—"} · β {pair.hedge_ratio.toFixed(4)} ·
        half-life {pair.half_life.toFixed(1)}h. Entry prices are captured at the
        current market on record.
      </p>

      <CapitalField
        label={`Capital — Leg 1 (${pair.base_market}) USD`}
        value={leg1}
        onChange={setLeg1}
        disabled={busy}
        testid="capital-leg1"
      />
      <CapitalField
        label={`Capital — Leg 2 (${pair.quote_market}) USD`}
        value={leg2}
        onChange={setLeg2}
        disabled={busy}
        testid="capital-leg2"
      />

      {busy && (
        <p
          className="mt-3 flex items-center gap-2 text-sm text-blue"
          data-testid="record-progress"
        >
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue/30 border-t-blue" />
          Recording… fetching live prices, please wait.
        </p>
      )}

      {error && <p className="mt-3 text-sm text-red">{error}</p>}

      <div className="mt-5 flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded border border-border px-3 py-1.5 text-xs text-muted hover:text-text"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={!valid || busy}
          data-testid="record-confirm"
          className="rounded border border-green px-3 py-1.5 text-xs text-green hover:bg-green/10 disabled:opacity-40"
        >
          {busy ? "Recording…" : "Record trade"}
        </button>
      </div>
    </Modal>
  );
}

function CapitalField({
  label,
  value,
  onChange,
  disabled,
  testid,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  testid: string;
}) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-xs text-muted">{label}</span>
      <input
        type="number"
        min="0"
        step="1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testid}
        className="w-full rounded border border-border bg-bg px-2 py-1.5 text-sm text-text focus:border-blue focus:outline-none disabled:opacity-50"
      />
    </label>
  );
}
