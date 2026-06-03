"""
Bot-client seam — the thin Telegram-send surface the gate and alerter depend on.

Both :class:`~telegrambot.gate.TelegramApprovalGate` and
:class:`~telegrambot.alerter.TelegramAlerter` talk only to this ``BotClient``
protocol, never to ``python-telegram-bot`` directly. That keeps them:

  * **testable without the library** — a test injects a fake ``BotClient`` and
    drives approve/reject/timeout entirely in-process (PTB is not installed in the
    venv; it is lazy-imported here, exactly like ``dydx-v4-client``), and
  * **free of PTB-specific keyboard plumbing** — building the inline ✅/❌ keyboard
    lives in :class:`PtbBotClient`, the one place that imports ``telegram``.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class BotClient(Protocol):
    """The minimal Telegram surface the gate/alerter need."""

    async def send_approval_request(
        self, *, text: str, approve_data: str, reject_data: str
    ) -> int | None:
        """Post ``text`` with ✅/❌ inline buttons carrying the callback payloads.

        Returns the sent message id (so it can be edited once decided), or
        ``None`` if the send failed.
        """
        ...

    async def edit_message(self, *, message_id: int, text: str) -> None:
        """Replace a previously-sent message's text and drop its keyboard."""
        ...

    async def send_message(self, *, text: str) -> None:
        """Post a plain notification (no buttons)."""
        ...


class PtbBotClient:
    """``BotClient`` backed by a real ``telegram.Bot`` for one operator chat.

    ``python-telegram-bot`` is imported lazily so importing this module (and the
    whole ``telegrambot`` package) never requires the library — only constructing
    a live client does. Every method swallows network/Telegram errors and logs
    them: a failed *notification* must never crash a trading pass, and a failed
    *approval send* surfaces to the gate as ``None`` (→ the signal times out and
    is auto-rejected, the safe default).
    """

    def __init__(self, *, token: str, chat_id: str) -> None:
        from telegram import Bot  # lazy: only a live client needs PTB

        self._bot = Bot(token=token)
        self._chat_id = chat_id

    @classmethod
    def from_bot(cls, bot, chat_id: str) -> "PtbBotClient":
        """Wrap an existing ``telegram.Bot`` (e.g. the PTB Application's) so the
        client and the update-polling Application share one HTTP session."""
        self = cls.__new__(cls)
        self._bot = bot
        self._chat_id = chat_id
        return self

    @property
    def bot(self):  # exposed so runtime.py can share one Bot with the Application
        return self._bot

    async def send_approval_request(
        self, *, text: str, approve_data: str, reject_data: str
    ) -> int | None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=approve_data),
                    InlineKeyboardButton("❌ Reject", callback_data=reject_data),
                ]
            ]
        )
        try:
            msg = await self._bot.send_message(
                chat_id=self._chat_id, text=text, reply_markup=keyboard
            )
            return msg.message_id
        except Exception as exc:  # network / auth / chat errors
            logger.error("Telegram approval send failed: %s", exc)
            return None

    async def edit_message(self, *, message_id: int, text: str) -> None:
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id, message_id=message_id, text=text
            )
        except Exception as exc:
            logger.warning("Telegram edit_message failed: %s", exc)

    async def send_message(self, *, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=text)
        except Exception as exc:
            logger.error("Telegram send_message failed: %s", exc)
