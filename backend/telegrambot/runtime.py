"""
Telegram runtime — PTB ``Application`` lifecycle + callback wiring + install.

This is the one module that drives ``python-telegram-bot`` (lazy-imported), so the
gate/alerter stay library-free and testable. :func:`start_telegram`:

  1. builds a PTB ``Application`` for the configured bot token,
  2. wraps its ``Bot`` in a :class:`~telegrambot.client.PtbBotClient`,
  3. constructs the :class:`~telegrambot.gate.TelegramApprovalGate` +
     :class:`~telegrambot.alerter.TelegramAlerter` and **installs them** behind the
     Phase-5a seams via ``set_approval_gate`` / ``set_alerter`` (ADR-0004 — no
     engine changes), and
  4. registers a ``CallbackQueryHandler`` that turns a ✅/❌ button tap into
     ``gate.resolve(token, approved)``, then starts polling for updates.

Called best-effort from the FastAPI lifespan: if Telegram isn't configured
(:data:`config.TELEGRAM_ENABLED` is False) or PTB isn't installed, it logs and
returns, leaving the ``AutoApproveGate``/``LoggingAlerter`` defaults in place so
every other phase keeps working.
"""

from __future__ import annotations

import logging

import config
from telegrambot.alerter import TelegramAlerter
from telegrambot.client import PtbBotClient
from telegrambot.gate import TelegramApprovalGate

logger = logging.getLogger(__name__)

# Module-level handle so the lifespan can stop what it started.
_application = None
_gate: TelegramApprovalGate | None = None


async def _on_callback(update, context) -> None:
    """PTB handler: a ✅/❌ tap → resolve the matching approval future."""
    query = update.callback_query
    if query is None:
        return
    # Only honour taps from the configured operator chat (ignore anyone else who
    # somehow reaches the bot).
    chat = query.message.chat if query.message else None
    if chat is not None and str(chat.id) != str(config.TELEGRAM_CHAT_ID):
        await query.answer("Not authorised.")
        return

    parsed = TelegramApprovalGate.parse_callback(query.data or "")
    if parsed is None:
        await query.answer()
        return
    token, approved = parsed
    matched = _gate.resolve(token, approved) if _gate is not None else False
    # Acknowledge the tap so Telegram clears the button's spinner. The full
    # message edit (with the decision) is done by the gate's request() path.
    await query.answer("Recorded." if matched else "Already decided / expired.")


async def start_telegram() -> bool:
    """Connect to Telegram and install the gate + alerter. Returns True if active.

    Best-effort: any failure (PTB missing, bad token, network) is logged and the
    defaults are left untouched.
    """
    global _application, _gate

    if not config.TELEGRAM_ENABLED:
        logger.info("Telegram not configured — using auto-approve gate + logging alerter.")
        return False
    if _application is not None:
        logger.info("Telegram already started.")
        return True

    try:
        from telegram.ext import Application, CallbackQueryHandler
    except ImportError:
        logger.warning(
            "python-telegram-bot not installed — Telegram approval disabled. "
            "Install it (it is in requirements.txt) to enable the approval flow."
        )
        return False

    try:
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CallbackQueryHandler(_on_callback))

        client = PtbBotClient.from_bot(application.bot, config.TELEGRAM_CHAT_ID)
        timeout_s = config.TELEGRAM_APPROVAL_TIMEOUT_MIN * 60.0
        gate = TelegramApprovalGate(client, timeout_s=timeout_s)
        alerter = TelegramAlerter(client)

        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        # Install only after polling is live so a tapped button can be resolved.
        from trading.alerts import set_alerter
        from trading.approval import set_approval_gate

        set_approval_gate(gate)
        set_alerter(alerter)

        _application = application
        _gate = gate
        logger.info("Telegram approval gate + alerter installed (timeout %.0fs).", timeout_s)
        return True
    except Exception as exc:  # bad token, network, etc.
        logger.error("Telegram startup failed (%s) — keeping default gate/alerter.", exc)
        _application = None
        _gate = None
        return False


async def stop_telegram() -> None:
    """Stop polling and shut the Application down cleanly (best-effort)."""
    global _application, _gate
    app = _application
    _application = None
    _gate = None
    if app is None:
        return
    try:
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        logger.warning("Telegram shutdown failed: %s", exc)
