"""Live trading engine (Phase 5a, PRD F5).

The execution core: atomic two-leg order placement (:class:`BotAgent`) with a
failsafe close + CODE-RED alarm, entry/exit managers built on the shared
``statcore`` signal rules, DB-backed ``LiveSession``/``LiveTrade`` state with real
P&L, behind an approval-gate seam (ADR-0004). dYdX is the only integrated
exchange; everything depends on the :class:`TradeClient` protocol so it is
testable with a fake.
"""

from trading.alerts import Alerter, LoggingAlerter, get_alerter, set_alerter
from trading.approval import (
    ApprovalGate,
    AutoApproveGate,
    RejectAllGate,
    get_approval_gate,
    set_approval_gate,
)
from trading.bot_agent import BotAgent
from trading.broker import OrderResult, Position, TradeClient
from trading.engine import LiveEngine, NoActiveSession, get_live_engine
from trading.entry import scan_for_entries
from trading.exit import manage_exits
from trading.pnl import LivePnl, compute_live_pnl

__all__ = [
    "Alerter",
    "LoggingAlerter",
    "get_alerter",
    "set_alerter",
    "ApprovalGate",
    "AutoApproveGate",
    "RejectAllGate",
    "get_approval_gate",
    "set_approval_gate",
    "BotAgent",
    "OrderResult",
    "Position",
    "TradeClient",
    "LiveEngine",
    "NoActiveSession",
    "get_live_engine",
    "scan_for_entries",
    "manage_exits",
    "LivePnl",
    "compute_live_pnl",
]
