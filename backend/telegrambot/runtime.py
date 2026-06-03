"""
Telegram runtime — PTB ``Application`` lifecycle + callback wiring + install.

This is the one module that drives ``python-telegram-bot`` (lazy-imported), so the
gate/alerter stay library-free and testable. :func:`start_telegram`:

  1. builds a PTB ``Application`` for the configured bot token,
  2. wraps its ``Bot`` in a :class:`~telegrambot.client.PtbBotClient`,
  3. constructs the :class:`~telegrambot.gate.TelegramApprovalGate` +
     :class:`~telegrambot.alerter.TelegramAlerter` and **installs them** behind the
     Phase-5a seams via ``set_approval_gate`` / ``set_alerter`` (ADR-0004 — no
     engine changes),
  4. registers a ``CallbackQueryHandler`` that turns a ✅/❌ button tap into
     ``gate.resolve(token, approved)``, and the F9.2 ``CommandHandler``s
     (``/status /balance /positions /pairs /cancel /activate /deactivate /help``)
     backed by :class:`~telegrambot.commands.CommandService`, then starts polling.

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
from telegrambot.commands import CommandService
from telegrambot.gate import TelegramApprovalGate

logger = logging.getLogger(__name__)

# Module-level handle so the lifespan can stop what it started.
_application = None
_gate: TelegramApprovalGate | None = None
_commands: CommandService | None = None


def _chat_authorised(update) -> bool:
    """True if the update came from the configured operator chat (or none set)."""
    chat = update.effective_chat if update is not None else None
    return chat is None or str(chat.id) == str(config.TELEGRAM_CHAT_ID)


async def _reply(update, text: str) -> None:
    if update is not None and update.message is not None:
        await update.message.reply_text(text)


# ── command handlers (PRD F9.2) ───────────────────────────────────────────────
# One factory builds every handler: authorise the chat, delegate to the named
# CommandService method, reply with its text. All command logic + error handling
# lives in CommandService (PTB-free, tested); these wrappers stay uniform so the
# auth/None-guard policy can't drift between commands.


def _make_command(method_name: str, *, sync: bool = False, with_args: bool = False):
    async def _handler(update, context) -> None:
        if not _chat_authorised(update) or _commands is None:
            return
        method = getattr(_commands, method_name)
        if sync:
            text = method()
        elif with_args:
            text = await method(list(context.args or []))
        else:
            text = await method()
        await _reply(update, text)

    return _handler


_cmd_status = _make_command("status")
_cmd_balance = _make_command("balance")
_cmd_positions = _make_command("positions")
_cmd_pairs = _make_command("pairs")
_cmd_cancel = _make_command("cancel", with_args=True)
_cmd_activate = _make_command("activate")
_cmd_deactivate = _make_command("deactivate")
_cmd_help = _make_command("help", sync=True)


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
    global _application, _gate, _commands

    if not config.TELEGRAM_ENABLED:
        logger.info("Telegram not configured — using auto-approve gate + logging alerter.")
        return False
    if _application is not None:
        logger.info("Telegram already started.")
        return True

    try:
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
    except ImportError:
        logger.warning(
            "python-telegram-bot not installed — Telegram approval disabled. "
            "Install it (it is in requirements.txt) to enable the approval flow."
        )
        return False

    try:
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CallbackQueryHandler(_on_callback))

        # F9.2 command handlers, backed by the live engine + scan repository.
        from db.scan_repository import get_scan_repository
        from trading.engine import get_live_engine

        _commands = CommandService(
            engine=get_live_engine(),
            scan_repo=get_scan_repository(),
            exchange=config.DEFAULT_EXCHANGE,
            mode=config.DEFAULT_MODE,
        )
        for name, handler in (
            ("status", _cmd_status),
            ("balance", _cmd_balance),
            ("positions", _cmd_positions),
            ("pairs", _cmd_pairs),
            ("cancel", _cmd_cancel),
            ("activate", _cmd_activate),
            ("deactivate", _cmd_deactivate),
            ("help", _cmd_help),
            ("start", _cmd_help),
        ):
            application.add_handler(CommandHandler(name, handler))

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
    global _application, _gate, _commands
    app = _application
    _application = None
    _gate = None
    _commands = None
    if app is None:
        return
    try:
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        logger.warning("Telegram shutdown failed: %s", exc)
