"""
Live Manual Trading (Phase 4, PRD F4).

The operator records a trade by hand off a bot signal; the entry prices for both
legs are captured at record time, and the per-leg P&L is computed from
user-supplied exit prices when the trade is marked CLOSED.

  * ``pnl`` — pure P&L math (no DB / no I/O).
  * ``repository`` — the Prisma persistence seam (+ singleton accessor).
"""

from __future__ import annotations

from .pnl import ManualPnl, compute_manual_pnl

__all__ = ["ManualPnl", "compute_manual_pnl"]
