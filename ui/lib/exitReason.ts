// Exit-reason presentation — shared by the backtest blotter and the per-trade
// chart so both read the same way.
//
// The exit *reason* is a signal rule (z-score reverted / z-score stop / time
// stop), decided in backend/statcore/signals.py — it is NOT the dollar result.
// A TAKE_PROFIT ("Reverted") can still be a net loss once fees + funding are
// netted out. So the badge is deliberately P&L-NEUTRAL: it never uses green,
// because green means "made money" everywhere else in the UI (the Net P&L
// column). Money-green/red lives only on the P&L number; the reason badge only
// encodes planned-exit (blue) vs risk-exit (amber/red) vs forced (grey).

/** Human label for a raw exit-reason enum (falls back to the raw value). */
export function reasonLabel(reason: string): string {
  switch (reason) {
    case "TAKE_PROFIT":
      return "Reverted";
    case "STOP_LOSS_ZSCORE":
      return "Z-stop";
    case "STOP_LOSS_TIME":
      return "Time-stop";
    case "END_OF_WINDOW":
      return "Window end";
    case "STOPPED":
      return "Stopped";
    default:
      return reason;
  }
}

/** One-line explanation of what the reason means (for a tooltip / title). */
export function reasonHint(reason: string): string {
  switch (reason) {
    case "TAKE_PROFIT":
      return "Reverted: |z| fell back inside the exit band — the mean-reversion thesis played out. This is the exit trigger, not the dollar result; it can still be a net loss after fees & funding.";
    case "STOP_LOSS_ZSCORE":
      return "Z-stop: |z| diverged past the stop threshold — the spread kept widening (possible cointegration breakdown).";
    case "STOP_LOSS_TIME":
      return "Time-stop: held longer than the half-life limit without reverting.";
    case "END_OF_WINDOW":
      return "Window end: force-closed when the trade window ended.";
    case "STOPPED":
      return "Stopped: the run was stopped while the position was open.";
    default:
      return reason;
  }
}

// P&L-neutral badge colors. Planned exit = calm blue; risk exits = amber/red;
// forced/other = grey. No green (green is reserved for positive P&L).
const REASON_COLOR: Record<string, string> = {
  TAKE_PROFIT: "#4a90e2", // Reverted — planned exit (blue, NOT green)
  STOP_LOSS_ZSCORE: "#ff4757", // Z-stop — breakdown (red)
  STOP_LOSS_TIME: "#ffd32a", // Time-stop — stale (amber)
  END_OF_WINDOW: "#8b949e", // forced (grey)
  STOPPED: "#8b949e",
};

/** Inline style for the reason pill: a P&L-neutral color on a faint tint. */
export function reasonBadgeStyle(reason: string): {
  color: string;
  backgroundColor: string;
} {
  const c = REASON_COLOR[reason] ?? "#4a90e2";
  return { color: c, backgroundColor: `${c}1a` };
}
