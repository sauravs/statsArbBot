"use client";

import { useState } from "react";
import { deleteManualTrade, type ManualTrade } from "@/lib/api";
import Modal from "./Modal";

// Hard-delete confirmation (issue #55): removing a manual trade is permanent, so
// the operator must confirm the destructive-action warning before it happens.
export default function DeleteManualTradeModal({
  trade,
  onClose,
  onDeleted,
}: {
  trade: ManualTrade;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await deleteManualTrade(trade.id);
      onDeleted();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete trade");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Delete record — ${trade.base_market} / ${trade.quote_market}`}
      onClose={onClose}
      testid="delete-modal"
    >
      <p className="mb-4 text-sm text-red" data-testid="delete-warning">
        Warning! This will permanently delete the record from the database.
        Proceed with caution.
      </p>

      {error && <p className="mt-3 text-sm text-red">{error}</p>}

      <div className="mt-5 flex justify-end gap-2">
        <button
          onClick={onClose}
          disabled={busy}
          className="rounded border border-border px-3 py-1.5 text-xs text-muted hover:text-text disabled:opacity-40"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={busy}
          data-testid="delete-confirm"
          className="rounded border border-red px-3 py-1.5 text-xs text-red hover:bg-red/10 disabled:opacity-40"
        >
          {busy ? "Deleting…" : "Delete permanently"}
        </button>
      </div>
    </Modal>
  );
}
