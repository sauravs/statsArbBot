"""
Approval gate (ADR-0004) — the human-in-the-loop seam the trading engine consults
before executing a signal.

The engine asks the gate to approve each entry/exit *before* placing orders. A
**stub** gate is used through Phase 8; the real Telegram approval flow drops in at
Phase 9 by implementing the same ``ApprovalGate`` protocol — with no engine
changes. This indirection is exactly what kept the prototype's Telegram coupling
out of the execution path (see ADR-0004 Context).

Signal shape (a plain dict so the gate stays decoupled from engine dataclasses):

    {"kind": "entry"|"exit", "base_market": str, "quote_market": str,
     "z_score": float, "reason": str | None, ...}
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ApprovalGate(Protocol):
    """Decides whether a pending entry/exit signal may execute."""

    async def request(self, signal: dict) -> bool:
        """Return True to execute the signal, False to skip it."""
        ...


class AutoApproveGate:
    """Approve every signal — the no-human-in-the-loop default (forward_test/tests)."""

    async def request(self, signal: dict) -> bool:  # noqa: D102
        logger.info(
            "Approval gate (auto): approving %s %s/%s",
            signal.get("kind"),
            signal.get("base_market"),
            signal.get("quote_market"),
        )
        return True


class RejectAllGate:
    """Reject every signal — a kill-switch / dry-run gate."""

    async def request(self, signal: dict) -> bool:  # noqa: D102
        logger.info(
            "Approval gate (reject-all): skipping %s %s/%s",
            signal.get("kind"),
            signal.get("base_market"),
            signal.get("quote_market"),
        )
        return False


# Process-wide gate singleton. Phase 9 will replace the default with the Telegram
# gate via ``set_approval_gate`` at startup; until then everything auto-approves.
_gate: ApprovalGate | None = None


def get_approval_gate() -> ApprovalGate:
    """Return the process-wide approval gate (defaults to :class:`AutoApproveGate`)."""
    global _gate
    if _gate is None:
        _gate = AutoApproveGate()
    return _gate


def set_approval_gate(gate: ApprovalGate) -> None:
    """Install a different gate (Phase 9 Telegram, or a test double)."""
    global _gate
    _gate = gate
