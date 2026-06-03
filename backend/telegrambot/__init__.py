"""
Telegram integration (Phase 9, ADR-0009) — the real human-in-the-loop approval
gate + operator alerter that drop in behind the Phase-5a ``ApprovalGate`` /
``Alerter`` seams (ADR-0004) with no engine changes.

The package is named ``telegrambot`` (not ``telegram``) on purpose: ``telegram``
is the import name of the ``python-telegram-bot`` library and a sibling package by
that name on ``sys.path`` (backend/) would shadow it. The same reason the
reference prototype used ``telegram_bot.py``.

Phase 9.0 ships the approval flow (PRD F9.1): ``TelegramApprovalGate`` (approve /
reject / timeout) + ``TelegramAlerter`` (CODE-RED). The command handlers
(``/status``, ``/balance``, …, PRD F9.2) arrive in Phase 9.1.

Layering mirrors the rest of the backend (pure logic + thin client seam):
  * ``client.py``  — ``BotClient`` protocol + ``PtbBotClient`` (lazy PTB import).
  * ``gate.py``    — ``TelegramApprovalGate`` (depends only on ``BotClient``).
  * ``alerter.py`` — ``TelegramAlerter`` (depends only on ``BotClient``).
  * ``runtime.py`` — PTB ``Application`` lifecycle + callback wiring + install.
The gate/alerter are therefore testable with a fake ``BotClient`` and never need
``python-telegram-bot`` installed (it is lazy-imported, like ``dydx-v4-client``).
"""

from __future__ import annotations

from telegrambot.alerter import TelegramAlerter
from telegrambot.client import BotClient
from telegrambot.gate import TelegramApprovalGate

__all__ = ["BotClient", "TelegramApprovalGate", "TelegramAlerter"]
