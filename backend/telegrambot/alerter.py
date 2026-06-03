"""
Telegram alerter (PRD F9) — the operator notification + CODE-RED channel.

Drops in behind the Phase-5a :class:`~trading.alerts.Alerter` seam: ``notify``
posts informational notices (trade opened/closed, guard tripped) and ``code_red``
posts the critical 🚨 alarm for a naked leg the bot could not unwind — the exact
case the reference prototype hard-coded a Telegram ``send_message`` + ``exit(1)``
for, now decoupled (ADR-0004).

Per the ``Alerter`` contract these methods **must never raise**; the underlying
:class:`~telegrambot.client.BotClient` already swallows and logs send failures, so
a dead Telegram channel can never abort a trading pass.
"""

from __future__ import annotations

import logging

from telegrambot.client import BotClient

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """``Alerter`` that posts to the operator's Telegram chat."""

    def __init__(self, client: BotClient) -> None:
        self._client = client

    async def notify(self, message: str) -> None:
        logger.info("ALERT: %s", message)
        await self._send(f"ℹ️ {message}")

    async def code_red(self, message: str) -> None:
        logger.critical("🚨 CODE RED: %s", message)
        await self._send(f"🚨 CODE RED 🚨\n{message}")

    async def _send(self, text: str) -> None:
        # The Alerter contract is "must never raise" — the engine's CODE-RED path
        # depends on it. PtbBotClient already swallows send errors, but guard here
        # too so any BotClient (incl. a misbehaving one) can't abort a trading pass.
        try:
            await self._client.send_message(text=text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("TelegramAlerter send failed (suppressed): %s", exc)
