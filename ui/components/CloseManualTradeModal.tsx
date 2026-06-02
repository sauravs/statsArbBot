"use client";

import { useState } from "react";
import { closeManualTrade, type ManualTrade } from "@/lib/api";
import Modal from "./Modal";

// Mark-closed popup (PRD F4.7): collect exit prices for both legs; the server
// computes and stores the realised P&L and flips status → CLOSED.
export default function CloseManualTradeModal({
  trade,
  onClose,
  onClosed,
}: {
  trade: ManualTrade;
  onClose: () => void;
  onClosed: () => void;
}) {
  const [exit1, setExit1] = useState(trade.entry_price_leg1.toFixed(4));
  const [exit2, setExit2] = useState(trade.entry_price_leg2.toFixed(4));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const e1 = parseFloat(exit1);
  const e2 = parseFloat(exit2);
  const valid = e1 > 0 && e2 > 0;

  async function submit() {
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await closeManualTrade(trade.id, { exit_price_leg1: e1, exit_price_leg2: e2 });
      onClosed();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to close trade");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Close trade — ${trade.base_market} / ${trade.quote_market}`}
      onClose={onClose}
      testid="close-modal"
    >
      <p className="mb-4 text-xs text-muted">
        Entry: {trade.base_market} {trade.entry_price_leg1.toFixed(4)} ·{" "}
        {trade.quote_market} {trade.entry_price_leg2.toFixed(4)}. Enter exit prices
        to realise P&L.
      </p>

      <PriceField
        label={`Exit price — ${trade.base_market}`}
        value={exit1}
        onChange={setExit1}
        testid="exit-leg1"
      />
      <PriceField
        label={`Exit price — ${trade.quote_market}`}
        value={exit2}
        onChange={setExit2}
        testid="exit-leg2"
      />

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
          data-testid="close-confirm"
          className="rounded border border-yellow px-3 py-1.5 text-xs text-yellow hover:bg-yellow/10 disabled:opacity-40"
        >
          {busy ? "Closing…" : "Close & compute P&L"}
        </button>
      </div>
    </Modal>
  );
}

function PriceField({
  label,
  value,
  onChange,
  testid,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testid: string;
}) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-xs text-muted">{label}</span>
      <input
        type="number"
        min="0"
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        className="w-full rounded border border-border bg-bg px-2 py-1.5 text-sm text-text focus:border-blue focus:outline-none"
      />
    </label>
  );
}
