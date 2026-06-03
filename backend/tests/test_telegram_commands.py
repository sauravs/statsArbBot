"""
Telegram command handlers (Phase 9.1, PRD F9.2 — ``/status /balance /positions
/pairs /cancel /activate /deactivate``).

The :class:`CommandService` is driven against a **real** ``LiveEngine`` wired to
the in-memory ``FakeLiveRepository`` + ``FakeTradeClient`` (the established Phase-5a
mocked-dYdX seam) plus a ``FakeScanRepository`` — so the commands, the engine's
``close_pair`` (the ``connect_dydx`` bug fix), and account/session reads are all
exercised with no ``python-telegram-bot`` and no network.

The thin PTB wrappers (chat auth + reply) in ``telegrambot.runtime`` are covered
separately at the bottom with a fake Update.
"""

from __future__ import annotations

import config
import telegrambot.runtime as runtime
import trading.engine as engine_module
from telegrambot.commands import CommandService, _fmt
from tests.conftest import FakeLiveRepository, FakeScanRepository, FakeTradeClient
from trading.engine import LiveEngine

EX, MODE = "dydx", "forward_test"


def _service(monkeypatch, *, prices=None, free=4321.0, equity=8765.0, fail_close=None):
    repo = FakeLiveRepository()
    trade_client = FakeTradeClient(
        prices=prices or {"AAA-USD": 100.0, "BBB-USD": 50.0},
        free_collateral=free,
        equity=equity,
        fail_close_markets=fail_close,
    )

    async def _mk():
        return trade_client

    monkeypatch.setattr(engine_module, "get_live_repository", lambda: repo)
    monkeypatch.setattr(engine_module, "make_trade_client", _mk)

    scan_repo = FakeScanRepository()
    svc = CommandService(
        engine=LiveEngine(), scan_repo=scan_repo, exchange=EX, mode=MODE
    )
    return svc, repo, trade_client, scan_repo


async def _seed_open_trade(repo, *, base="AAA-USD", quote="BBB-USD", z=2.5):
    session = await repo.start_session(exchange=EX, mode=MODE)
    return await repo.create_trade(
        {
            "session_id": session["id"],
            "exchange": EX,
            "mode": MODE,
            "status": "OPEN",
            "base_market": base,
            "quote_market": quote,
            "base_side": "BUY",
            "quote_side": "SELL",
            "base_size": 1.0,
            "quote_size": 2.0,
            "entry_price_leg1": 100.0,
            "entry_price_leg2": 50.0,
            "entry_z_score": z,
            "hedge_ratio": 1.0,
            "half_life": 10.0,
            "opened_at": "2025-01-01T00:00:00+00:00",
        }
    )


def _pair_row(base, quote, *, hl, p, z, zc):
    return {
        "base_market": base,
        "quote_market": quote,
        "hedge_ratio": 1.0,
        "intercept": 0.0,
        "half_life": hl,
        "zero_crossings": zc,
        "p_value": p,
        "z_score": z,
        "spread_std": 1.0,
        "scanned_at": None,
        "window_start": None,
        "window_end": None,
        "exchange": EX,
        "mode": MODE,
    }


# ── /status ───────────────────────────────────────────────────────────────────


async def test_status_inactive_when_no_session(monkeypatch):
    svc, *_ = _service(monkeypatch)
    text = await svc.status()
    assert "Active: ❌ no" in text
    assert "Open pairs: 0" in text


async def test_status_active_with_open_count(monkeypatch):
    svc, repo, *_ = _service(monkeypatch)
    await _seed_open_trade(repo)
    text = await svc.status()
    assert "Active: ✅ yes" in text
    assert "Open pairs: 1" in text


# ── /balance ──────────────────────────────────────────────────────────────────


async def test_balance_formats_account(monkeypatch):
    svc, *_ = _service(monkeypatch, free=4321.0, equity=8765.5)
    text = await svc.balance()
    assert "$8,765.50" in text
    assert "$4,321.00" in text


# ── /positions ────────────────────────────────────────────────────────────────


async def test_positions_empty(monkeypatch):
    svc, *_ = _service(monkeypatch)
    assert await svc.positions() == "No open positions."


async def test_positions_lists_open_trades(monkeypatch):
    svc, repo, *_ = _service(monkeypatch)
    await _seed_open_trade(repo, z=-2.34)
    text = await svc.positions()
    assert "AAA-USD BUY" in text and "BBB-USD SELL" in text
    assert "entry Z=-2.34" in text


async def test_positions_renders_nan_z_as_placeholder(monkeypatch):
    svc, repo, *_ = _service(monkeypatch)
    await _seed_open_trade(repo, z=float("nan"))
    text = await svc.positions()
    assert "entry Z=—" in text  # NaN → fallback, not the literal "nan"


def test_fmt_guards_non_finite():
    assert _fmt(float("nan"), ",.2f") == "—"
    assert _fmt(float("inf"), ",.2f") == "—"
    assert _fmt(None, ",.2f") == "—"
    assert _fmt(1234.5, ",.2f") == "1,234.50"


# ── /pairs ────────────────────────────────────────────────────────────────────


async def test_pairs_empty(monkeypatch):
    svc, *_ = _service(monkeypatch)
    assert "run a scan" in await svc.pairs()


async def test_pairs_lists_top_five(monkeypatch):
    svc, _repo, _tc, scan_repo = _service(monkeypatch)
    rows = [
        _pair_row(f"M{i}-USD", "Q-USD", hl=10.0 + i, p=0.01, z=2.0, zc=20 - i)
        for i in range(7)
    ]
    await scan_repo.replace_scan_results(rows, exchange=EX, mode=MODE)
    text = await svc.pairs()
    assert "Top 5 cointegrated pairs" in text
    # 5 listed (+1 header line) — best zero_crossings first.
    assert len(text.splitlines()) == 6
    assert "M0-USD/Q-USD HL=10.0h p=0.0100 Z=+2.00" in text
    assert "M6-USD" not in text  # 6th-best dropped by the limit


# ── /cancel ───────────────────────────────────────────────────────────────────


async def test_cancel_usage_without_args(monkeypatch):
    svc, *_ = _service(monkeypatch)
    assert "Usage: /cancel" in await svc.cancel([])
    assert "Usage: /cancel" in await svc.cancel(["AAA-USD"])  # need two args


async def test_cancel_not_found(monkeypatch):
    svc, *_ = _service(monkeypatch)
    assert "No open position" in await svc.cancel(["AAA-USD", "BBB-USD"])


async def test_cancel_closes_pair_and_marks_closed(monkeypatch):
    svc, repo, trade_client, _ = _service(monkeypatch)
    await _seed_open_trade(repo)
    # Both legs live on the fake exchange.
    await trade_client.place_market_order(market="AAA-USD", side="BUY", size=1.0)
    await trade_client.place_market_order(market="BBB-USD", side="SELL", size=2.0)

    text = await svc.cancel(["aaa-usd", "bbb-usd"])  # lower-case → normalised

    assert "✅ Closed AAA-USD/BBB-USD" in text and "P&L=$" in text
    closed = await repo.list_trades(exchange=EX, mode=MODE, status="CLOSED")
    assert len(closed) == 1 and closed[0]["exit_reason"] == "CANCELLED"
    assert "AAA-USD" not in trade_client.positions
    assert "BBB-USD" not in trade_client.positions


async def test_cancel_reports_partial_close_failure(monkeypatch):
    svc, repo, trade_client, _ = _service(monkeypatch, fail_close={"AAA-USD"})
    await _seed_open_trade(repo)
    # Both legs live; the base leg's reduce-only close will fail.
    await trade_client.place_market_order(market="AAA-USD", side="BUY", size=1.0)
    await trade_client.place_market_order(market="BBB-USD", side="SELL", size=2.0)

    text = await svc.cancel(["AAA-USD", "BBB-USD"])

    assert "could not be fully closed" in text
    # Trade stays OPEN for the exit manager to retry.
    assert len(await repo.get_open_trades(exchange=EX, mode=MODE)) == 1


async def test_cancel_reconciles_pair_already_flat(monkeypatch):
    # Legs already closed outside the bot (no positions on the exchange): /cancel
    # marks the stale trade CLOSED with pnl unknown rather than firing no-op orders.
    svc, repo, trade_client, _ = _service(monkeypatch)
    await _seed_open_trade(repo)

    text = await svc.cancel(["AAA-USD", "BBB-USD"])

    assert "✅ Closed AAA-USD/BBB-USD" in text and "P&L=unknown" in text
    assert trade_client.orders == []  # no reduce-only orders placed for flat legs
    closed = await repo.list_trades(exchange=EX, mode=MODE, status="CLOSED")
    assert len(closed) == 1 and closed[0]["pnl"] is None


async def test_cancel_unwinds_single_live_orphan_leg(monkeypatch):
    # One leg live, one already flat → close only the live leg; pnl unknown.
    svc, repo, trade_client, _ = _service(monkeypatch)
    await _seed_open_trade(repo)
    await trade_client.place_market_order(market="AAA-USD", side="BUY", size=1.0)

    text = await svc.cancel(["AAA-USD", "BBB-USD"])

    assert "✅ Closed AAA-USD/BBB-USD" in text and "P&L=unknown" in text
    assert "AAA-USD" not in trade_client.positions  # the live leg was unwound
    # Exactly one reduce-only order (for the live base leg).
    assert [o["market"] for o in trade_client.orders if o["reduce_only"]] == ["AAA-USD"]


# ── /activate, /deactivate ────────────────────────────────────────────────────


async def test_activate_starts_session(monkeypatch):
    svc, repo, *_ = _service(monkeypatch)
    text = await svc.activate()
    assert "activated" in text
    assert await repo.get_active_session(exchange=EX, mode=MODE) is not None


async def test_deactivate_stops_session(monkeypatch):
    svc, repo, *_ = _service(monkeypatch)
    await repo.start_session(exchange=EX, mode=MODE)
    text = await svc.deactivate()
    assert "deactivated" in text
    assert await repo.get_active_session(exchange=EX, mode=MODE) is None


# ── /help ─────────────────────────────────────────────────────────────────────


def test_help_lists_every_command(monkeypatch):
    svc, *_ = _service(monkeypatch)
    text = svc.help()
    for cmd in ("/status", "/balance", "/positions", "/pairs", "/cancel",
                "/activate", "/deactivate"):
        assert cmd in text


# ── defensive: a failing engine surfaces an error string, never raises ────────


async def test_command_swallows_engine_error(monkeypatch):
    class _Boom:
        async def get_session(self, **_):
            raise RuntimeError("db down")

        async def list_trades(self, **_):
            raise RuntimeError("db down")

    svc = CommandService(
        engine=_Boom(), scan_repo=FakeScanRepository(), exchange=EX, mode=MODE
    )
    text = await svc.status()
    assert text.startswith("⚠️") and "db down" in text


# ── runtime PTB wrappers: chat auth + reply plumbing (no PTB) ──────────────────


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeMessage:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text):
        self.replies.append(text)


class _FakeUpdate:
    def __init__(self, chat_id):
        self.effective_chat = _FakeChat(chat_id)
        self.message = _FakeMessage()


class _FakeContext:
    def __init__(self, args=None):
        self.args = args or []


class _StubCommands:
    async def status(self):
        return "STATUS-OK"


async def test_authorised_chat_gets_reply(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "555")
    monkeypatch.setattr(runtime, "_commands", _StubCommands())
    update = _FakeUpdate("555")
    await runtime._cmd_status(update, _FakeContext())
    assert update.message.replies == ["STATUS-OK"]


async def test_foreign_chat_is_ignored(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "555")
    monkeypatch.setattr(runtime, "_commands", _StubCommands())
    update = _FakeUpdate("999")  # not the operator
    await runtime._cmd_status(update, _FakeContext())
    assert update.message.replies == []


async def test_cancel_wrapper_passes_args(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "555")

    captured = {}

    class _C:
        async def cancel(self, args):
            captured["args"] = args
            return "ok"

    monkeypatch.setattr(runtime, "_commands", _C())
    update = _FakeUpdate("555")
    await runtime._cmd_cancel(update, _FakeContext(args=["BTC-USD", "ETH-USD"]))
    assert captured["args"] == ["BTC-USD", "ETH-USD"]
    assert update.message.replies == ["ok"]
