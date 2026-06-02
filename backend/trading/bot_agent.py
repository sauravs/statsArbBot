"""
Atomic two-leg trade executor (PRD §3.2, F5.2) — the safety-critical core.

Opens both legs of a pair as one logical unit and guarantees the account is never
left with a naked single-leg position:

  1. Place leg 1 (base); wait for it to confirm filled.
  2. Place leg 2 (quote); wait for it to confirm filled.
  3. If leg 2 fails (submission or fill timeout) *after* leg 1 filled → immediately
     place a reduce-only **failsafe close** on leg 1.
  4. If the failsafe close itself fails → raise a **CODE RED** alert (a naked leg
     needs a human now).

This preserves the reference bot's critical safety logic (initial-codebase-
analysis.md §Critical-Safety-Logic) but, unlike the prototype, depends only on the
:class:`~trading.broker.TradeClient` and :class:`~trading.alerts.Alerter`
protocols — no global Telegram, no ``exit(1)`` — so it is unit-testable with fakes.

Fills are confirmed by polling for the position to appear (dYdX market orders are
short-term FOK; a filled order shows up as an open position), bounded by
``MAX_ORDER_WAIT_SECS``.
"""

from __future__ import annotations

import asyncio
import logging

import config
from statcore.signals import Side
from trading.alerts import Alerter
from trading.broker import OrderResult, TradeClient

logger = logging.getLogger(__name__)


def _opposite(side: str) -> str:
    """The reduce-only close side for a leg opened with ``side``."""
    return Side.SELL.value if side == Side.BUY.value else Side.BUY.value


class BotAgent:
    """Executes one pair's two legs atomically with a failsafe + CODE-RED guard."""

    def __init__(
        self,
        client: TradeClient,
        alerter: Alerter,
        *,
        base_market: str,
        quote_market: str,
        base_side: str,
        quote_side: str,
        base_size: float,
        quote_size: float,
        entry_z_score: float,
        hedge_ratio: float,
        half_life: float,
        max_wait_secs: float | None = None,
        poll_interval: float | None = None,
    ) -> None:
        self.client = client
        self.alerter = alerter
        self.base_market = base_market
        self.quote_market = quote_market
        self.base_side = base_side
        self.quote_side = quote_side
        self.base_size = base_size
        self.quote_size = quote_size
        self.entry_z_score = entry_z_score
        self.hedge_ratio = hedge_ratio
        self.half_life = half_life
        # Resolved from config at call time (not frozen at import) so tests can
        # shrink the polling and the live values stay tunable via env.
        self._max_wait_secs = (
            max_wait_secs if max_wait_secs is not None else config.MAX_ORDER_WAIT_SECS
        )
        self._poll_interval = (
            poll_interval if poll_interval is not None else config.ORDER_POLL_INTERVAL
        )

        self.status = "PENDING"  # PENDING | LIVE | ERROR
        self.base_order: OrderResult | None = None
        self.quote_order: OrderResult | None = None
        self.error: str | None = None

    async def open_trades(self) -> str:
        """
        Place both legs. Returns ``"LIVE"`` if both filled, else ``"ERROR"``
        (with the failsafe attempted and ``self.error`` set).
        """
        logger.info(
            "Opening pair %s/%s | %s %s / %s %s | Z=%.3f HL=%.1fh",
            self.base_market, self.quote_market,
            self.base_side, self.base_market, self.quote_side, self.quote_market,
            self.entry_z_score, self.half_life,
        )

        # ── Leg 1: base ──────────────────────────────────────────────────────
        self.base_order = await self.client.place_market_order(
            market=self.base_market, side=self.base_side, size=self.base_size
        )
        if self.base_order is None:
            return self._fail(f"Leg 1 ({self.base_market}) submission failed.")
        if not await self._wait_for_fill(self.base_market):
            return self._fail(f"Leg 1 ({self.base_market}) fill timed out.")
        logger.info("Leg 1 (%s) FILLED", self.base_market)

        # ── Leg 2: quote ─────────────────────────────────────────────────────
        self.quote_order = await self.client.place_market_order(
            market=self.quote_market, side=self.quote_side, size=self.quote_size
        )
        if self.quote_order is None:
            await self._failsafe_close_leg1()
            return self._fail(f"Leg 2 ({self.quote_market}) submission failed.")
        if not await self._wait_for_fill(self.quote_market):
            await self._failsafe_close_leg1()
            return self._fail(f"Leg 2 ({self.quote_market}) fill timed out.")
        logger.info("Leg 2 (%s) FILLED", self.quote_market)

        self.status = "LIVE"
        await self.alerter.notify(
            f"New trade opened: {self.base_market}/{self.quote_market} "
            f"({self.base_side} {self.base_market} / {self.quote_side} {self.quote_market}) "
            f"Z={self.entry_z_score:.3f}"
        )
        return "LIVE"

    # ── internals ────────────────────────────────────────────────────────────

    def _fail(self, reason: str) -> str:
        logger.warning("BotAgent %s/%s ERROR: %s", self.base_market, self.quote_market, reason)
        self.status = "ERROR"
        self.error = reason
        return "ERROR"

    async def _wait_for_fill(self, market: str) -> bool:
        """Poll until a position for ``market`` appears, or the deadline passes."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._max_wait_secs
        while loop.time() < deadline:
            await asyncio.sleep(self._poll_interval)
            if await self.client.is_open_position(market):
                return True
        return False

    async def _failsafe_close_leg1(self) -> None:
        """
        Try to unwind the already-filled leg 1 so no naked position remains.
        Raises a CODE-RED alert if the failsafe close cannot be placed.
        """
        close_side = _opposite(self.base_side)
        logger.warning(
            "Failsafe: closing leg 1 %s with reduce-only %s", self.base_market, close_side
        )
        result = await self.client.place_market_order(
            market=self.base_market,
            side=close_side,
            size=self.base_size,
            reduce_only=True,
        )
        if result is None:
            await self.alerter.code_red(
                f"{self.base_market} leg 1 is OPEN but the failsafe close FAILED. "
                f"Manual intervention required immediately."
            )

    def entry_snapshot(self) -> dict:
        """The filled-trade fields the live repository persists on a successful open."""
        return {
            "base_market": self.base_market,
            "quote_market": self.quote_market,
            "base_side": self.base_side,
            "quote_side": self.quote_side,
            "base_size": self.base_size,
            "quote_size": self.quote_size,
            "hedge_ratio": self.hedge_ratio,
            "half_life": self.half_life,
            "entry_z_score": self.entry_z_score,
            "entry_price_leg1": self.base_order.price if self.base_order else 0.0,
            "entry_price_leg2": self.quote_order.price if self.quote_order else 0.0,
        }
