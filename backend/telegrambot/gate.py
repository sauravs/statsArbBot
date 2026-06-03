"""
Telegram approval gate (PRD F9.1) — the real human-in-the-loop ``ApprovalGate``.

When the live engine offers a signal (``await gate.request(signal)``), this gate
posts an approve/reject prompt to the operator's Telegram chat and **blocks the
trading pass** until the operator taps a button or a timeout elapses:

  * ✅ tapped  → ``request`` returns ``True``  (execute the signal)
  * ❌ tapped  → ``request`` returns ``False`` (skip)
  * timeout    → ``request`` returns ``False`` (auto-reject — the safe default)

Mechanics: ``request`` creates an :class:`asyncio.Future`, registers it under a
random token, embeds that token in the buttons' ``callback_data``, then awaits the
future under :func:`asyncio.wait_for`. The PTB callback handler (wired in
``runtime.py``) parses the tapped button's token and calls :meth:`resolve`, which
completes the future. Because the engine serialises passes behind one lock only
one approval is ever outstanding, but futures are keyed by token so the gate is
correct even if that ever changes.

The gate depends only on :class:`~telegrambot.client.BotClient`, so it is fully
testable with a fake bot and no ``python-telegram-bot`` installed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from telegrambot.client import BotClient

logger = logging.getLogger(__name__)

_APPROVE = "approve"
_REJECT = "reject"


def _format_signal(signal: dict) -> str:
    """Render a signal dict as the operator-facing prompt text."""
    kind = str(signal.get("kind", "signal")).upper()
    base = signal.get("base_market", "?")
    quote = signal.get("quote_market", "?")
    z = signal.get("z_score")
    z_str = f"{z:+.2f}" if isinstance(z, (int, float)) else "n/a"
    lines = [
        f"🔔 {kind} signal — approve?",
        f"Pair: {base} / {quote}",
        f"Z-score: {z_str}",
    ]
    if signal.get("kind") == "entry" and signal.get("base_side"):
        lines.append(f"Sides: {base} {signal['base_side']} / {quote} {signal['quote_side']}")
    if signal.get("reason"):
        lines.append(f"Reason: {signal['reason']}")
    return "\n".join(lines)


class TelegramApprovalGate:
    """Approve/reject/timeout gate backed by a Telegram chat."""

    def __init__(self, client: BotClient, *, timeout_s: float) -> None:
        self._client = client
        self._timeout_s = timeout_s
        # token → the future awaiting the operator's decision. One per outstanding
        # request (the message id is held by request()'s local scope, not here).
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request(self, signal: dict) -> bool:
        """Prompt the operator and block until decided or timed out."""
        # A zero/negative timeout is a kill-switch: reject without prompting.
        if self._timeout_s <= 0:
            logger.info("Approval timeout is %.0fs — rejecting without prompt.", self._timeout_s)
            return False

        token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[token] = future

        text = _format_signal(signal)
        message_id = await self._client.send_approval_request(
            text=text,
            approve_data=f"{_APPROVE}:{token}",
            reject_data=f"{_REJECT}:{token}",
        )
        if message_id is None:
            # The prompt never reached the operator — fail safe (skip the signal)
            # rather than block the pass for the full timeout on a dead channel.
            self._pending.pop(token, None)
            logger.error("Approval prompt failed to send — skipping signal.")
            return False

        try:
            approved = await asyncio.wait_for(future, self._timeout_s)
        except asyncio.TimeoutError:
            logger.info("Approval timed out after %.0fs — auto-rejecting.", self._timeout_s)
            await self._client.edit_message(
                message_id=message_id, text=f"{text}\n\n⏳ Timed out — auto-rejected."
            )
            return False
        finally:
            self._pending.pop(token, None)

        decision = "✅ Approved" if approved else "❌ Rejected"
        await self._client.edit_message(message_id=message_id, text=f"{text}\n\n{decision}.")
        return approved

    def resolve(self, token: str, approved: bool) -> bool:
        """Complete the pending request for ``token``. Returns True if it matched.

        Called by the PTB callback handler when a button is tapped. A token that
        is unknown (already decided, timed out, or from a stale message) is
        ignored — the handler should answer the callback regardless.
        """
        future = self._pending.get(token)
        if future is None:
            return False
        if not future.done():
            future.set_result(approved)
        return True

    @staticmethod
    def parse_callback(data: str) -> tuple[str, bool] | None:
        """Parse a button's ``callback_data`` into ``(token, approved)``.

        Returns ``None`` for anything that isn't one of this gate's
        ``approve:``/``reject:`` payloads (so other handlers can coexist).
        """
        if not data or ":" not in data:
            return None
        action, _, token = data.partition(":")
        if action == _APPROVE:
            return token, True
        if action == _REJECT:
            return token, False
        return None
