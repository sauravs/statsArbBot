"""
Operator alerting seam — how the engine surfaces notices and the CODE-RED alarm.

The :class:`BotAgent` failsafe path (a leg-1 fill that can't be unwound) must
reach the operator loudly; the prototype hard-coded a Telegram ``send_message``
+ ``exit(1)`` there. We route through an :class:`Alerter` interface instead so
the execution core stays decoupled from Telegram (which arrives in Phase 9) and
is testable: a test injects a recording alerter and asserts ``code_red`` fired.

The default :class:`LoggingAlerter` just logs; Phase 9 supplies a Telegram-backed
implementation of the same protocol with no engine changes (ADR-0004).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Alerter(Protocol):
    """Sends operator notifications. Implementations must never raise."""

    async def notify(self, message: str) -> None:
        """Informational notice (trade opened/closed, guard tripped)."""
        ...

    async def code_red(self, message: str) -> None:
        """Critical alarm — a naked leg the bot could not unwind. Demands a human."""
        ...


class LoggingAlerter:
    """Default alerter: logs notices at INFO and CODE-RED at CRITICAL."""

    async def notify(self, message: str) -> None:  # noqa: D102
        logger.info("ALERT: %s", message)

    async def code_red(self, message: str) -> None:  # noqa: D102
        logger.critical("🚨 CODE RED: %s", message)


_alerter: Alerter | None = None


def get_alerter() -> Alerter:
    """Return the process-wide alerter (defaults to :class:`LoggingAlerter`)."""
    global _alerter
    if _alerter is None:
        _alerter = LoggingAlerter()
    return _alerter


def set_alerter(alerter: Alerter) -> None:
    """Install a different alerter (Phase 9 Telegram, or a test double)."""
    global _alerter
    _alerter = alerter
