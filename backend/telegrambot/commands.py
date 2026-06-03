"""
Telegram command logic (PRD F9.2) — pure reply-string builders over the live
engine + scan repository.

These back the ``/status /balance /positions /pairs /cancel /activate /deactivate``
handlers (plus ``/help``). Keeping the *logic* here — separate from the PTB
``CommandHandler`` plumbing in ``runtime.py`` — means the whole command surface is
testable with a fake engine and **no ``python-telegram-bot`` installed**, exactly
like the gate/alerter (ADR-0009).

Each method is defensive: it catches its own errors and returns an operator-facing
string, so a transient exchange/DB failure can never crash the PTB polling loop.

**``connect_dydx`` bug fix (PRD F9.2 / `initial-codebase-analysis.md`):** the
prototype's ``/cancel`` handler called ``create_dydx_connection`` — a name that did
not exist (the real function was ``connect_dydx``), so ``/cancel`` raised
``NameError`` at runtime. Here ``/cancel`` calls the real, named
:meth:`LiveEngine.close_pair`, so the bug cannot recur.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "📖 statsArbBot commands\n"
    "/status — bot active state + open pair count\n"
    "/balance — free collateral & equity\n"
    "/positions — open pairs (sides + entry Z)\n"
    "/pairs — top cointegrated pairs from the latest scan\n"
    "/cancel BASE QUOTE — immediately close one open pair\n"
    "/activate — start the live bot\n"
    "/deactivate — stop the live bot\n"
    "/help — this message"
)

# How many pairs /pairs lists (the prototype showed 5).
_PAIRS_LIMIT = 5


def _fmt(value, spec: str, fallback: str = "—") -> str:
    """Format a finite number with ``spec`` (e.g. ``,.2f``), else ``fallback``.

    Guards NaN/Inf explicitly — ``isinstance(float('nan'), float)`` is True, so
    without the ``isfinite`` check a NaN field would render as the literal "nan".
    """
    if isinstance(value, (int, float)) and math.isfinite(value):
        return format(value, spec)
    return fallback


class CommandService:
    """Builds the reply text for each Telegram command.

    Depends only on the live ``engine`` (session control + trades + account +
    ``close_pair``) and the ``scan_repo`` (latest cointegrated pairs), both injected
    so tests can drive the commands with fakes. All commands act on one
    ``(exchange, mode)`` — Telegram drives the live bot, so the operator's default
    deployment.
    """

    def __init__(self, *, engine, scan_repo, exchange: str, mode: str) -> None:
        self._engine = engine
        self._scan_repo = scan_repo
        self._exchange = exchange
        self._mode = mode

    def help(self) -> str:
        return HELP_TEXT

    async def status(self) -> str:
        try:
            session = await self._engine.get_session(
                exchange=self._exchange, mode=self._mode
            )
            open_trades = await self._engine.list_trades(
                exchange=self._exchange, mode=self._mode, status="OPEN"
            )
            active = bool(session and session.get("active"))
            return (
                "📊 Bot status\n"
                f"Mode: {self._exchange}/{self._mode}\n"
                f"Active: {'✅ yes' if active else '❌ no'}\n"
                f"Open pairs: {len(open_trades)}"
            )
        except Exception as exc:  # operator-facing — never propagate
            logger.error("/status failed: %s", exc)
            return f"⚠️ Could not read status: {exc}"

    async def balance(self) -> str:
        try:
            account = await self._engine.account_summary()
            free = _fmt(account.get("free_collateral"), ",.2f")
            equity = _fmt(account.get("equity"), ",.2f")
            return (
                "💰 Account\n"
                f"Equity: ${equity}\n"
                f"Free collateral: ${free}"
            )
        except Exception as exc:
            logger.error("/balance failed: %s", exc)
            return f"⚠️ Could not fetch balance: {exc}"

    async def positions(self) -> str:
        try:
            open_trades = await self._engine.list_trades(
                exchange=self._exchange, mode=self._mode, status="OPEN"
            )
            if not open_trades:
                return "No open positions."
            lines = ["📈 Open positions"]
            for t in open_trades:
                z = _fmt(t.get("entry_z_score"), "+.2f")
                lines.append(
                    f"• {t['base_market']} {t.get('base_side', '?')} / "
                    f"{t['quote_market']} {t.get('quote_side', '?')} | entry Z={z}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.error("/positions failed: %s", exc)
            return f"⚠️ Could not read positions: {exc}"

    async def pairs(self) -> str:
        try:
            pairs = await self._scan_repo.get_latest_pairs(
                exchange=self._exchange, mode=self._mode
            )
            if not pairs:
                return "No cointegrated pairs — run a scan first."
            lines = [f"🔗 Top {min(_PAIRS_LIMIT, len(pairs))} cointegrated pairs"]
            for p in pairs[:_PAIRS_LIMIT]:
                hl = _fmt(p.get("half_life"), ".1f")
                pv = _fmt(p.get("p_value"), ".4f")
                z = _fmt(p.get("z_score"), "+.2f")
                lines.append(
                    f"• {p['base_market']}/{p['quote_market']} "
                    f"HL={hl}h p={pv} Z={z}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.error("/pairs failed: %s", exc)
            return f"⚠️ Could not read pairs: {exc}"

    async def cancel(self, args: list[str]) -> str:
        if len(args) < 2:
            return "Usage: /cancel BASE QUOTE\nExample: /cancel BTC-USD ETH-USD"
        base = args[0].upper()
        quote = args[1].upper()
        try:
            result = await self._engine.close_pair(
                exchange=self._exchange,
                mode=self._mode,
                base_market=base,
                quote_market=quote,
            )
        except Exception as exc:
            logger.error("/cancel failed: %s", exc)
            return f"⚠️ Error closing {base}/{quote}: {exc}"

        if not result.get("found"):
            return f"⚠️ No open position for {base}/{quote}."
        if not result.get("closed"):
            return (
                f"⚠️ {base}/{quote} could not be fully closed — it may still be live. "
                "Check the dashboard."
            )
        pnl = result.get("pnl")
        # pnl is None when a leg had already closed outside the bot (fills unknown).
        pnl_str = f"${_fmt(pnl, ',.2f')}" if isinstance(pnl, (int, float)) else "unknown"
        return f"✅ Closed {base}/{quote} — P&L={pnl_str}."

    async def activate(self) -> str:
        try:
            await self._engine.start_session(exchange=self._exchange, mode=self._mode)
            return f"✅ Bot activated ({self._exchange}/{self._mode})."
        except Exception as exc:
            logger.error("/activate failed: %s", exc)
            return f"⚠️ Could not activate: {exc}"

    async def deactivate(self) -> str:
        try:
            await self._engine.stop_session(exchange=self._exchange, mode=self._mode)
            return f"⏹ Bot deactivated ({self._exchange}/{self._mode})."
        except Exception as exc:
            logger.error("/deactivate failed: %s", exc)
            return f"⚠️ Could not deactivate: {exc}"
