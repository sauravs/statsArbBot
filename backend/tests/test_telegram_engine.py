"""
Integration: the Telegram approval gate wired into the live entry/exit passes
(Phase 9.0, PRD F9.1 acceptance — "signal → prompt → approve/reject/timeout →
executes/skips").

Drives ``trading.entry.scan_for_entries`` / ``trading.exit.manage_exits`` directly
(the same functions the engine calls) with a real :class:`TelegramApprovalGate`
over a mocked Telegram ``FakeBotClient``. Proves the gate decision actually gates
order placement — no ``python-telegram-bot`` and no live exchange needed.
"""

from __future__ import annotations

import pytest

import config
import trading.entry as entry_module
import trading.exit as exit_module
from marketdata.pair_series import PairSnapshot
from telegrambot.alerter import TelegramAlerter
from telegrambot.gate import TelegramApprovalGate
from tests.conftest import FakeLiveRepository, FakeTradeClient
from tests.test_telegram_gate import FakeBotClient
from trading.entry import scan_for_entries
from trading.exit import manage_exits

PAIR = {
    "base_market": "AAA-USD",
    "quote_market": "BBB-USD",
    "hedge_ratio": 1.0,
    "intercept": 0.0,
    "half_life": 10.0,
}


@pytest.fixture
def fast_fills(monkeypatch):
    # Shrink fill polling so BotAgent resolves instantly.
    monkeypatch.setattr(config, "MAX_ORDER_WAIT_SECS", 0.1)
    monkeypatch.setattr(config, "ORDER_POLL_INTERVAL", 0.01)


def _patch_snapshot(monkeypatch, module, *, z: float):
    snap = PairSnapshot(base_price=100.0, quote_price=50.0, spread_value=0.0, z_score=z)

    async def _fake(*_a, **_k):
        return snap

    monkeypatch.setattr(module, "current_pair_snapshot", _fake)


def _make_gate(auto: bool | None, *, timeout_s: float = 5.0):
    client = FakeBotClient(auto=auto)
    gate = TelegramApprovalGate(client, timeout_s=timeout_s)
    client.gate = gate
    return gate, client


async def _run_entry(gate, client):
    repo = FakeLiveRepository()
    await repo.start_session(exchange="dydx", mode="forward_test")
    session = await repo.get_active_session(exchange="dydx", mode="forward_test")
    trade_client = FakeTradeClient(prices={"AAA-USD": 100.0, "BBB-USD": 50.0})
    return await scan_for_entries(
        trade_client=trade_client,
        data_client=object(),
        repo=repo,
        gate=gate,
        alerter=TelegramAlerter(client),
        pairs=[dict(PAIR)],
        session_id=session["id"],
        exchange="dydx",
        mode="forward_test",
    ), repo


# ── entry: approve opens, reject/timeout skip ────────────────────────────────


async def test_entry_approved_opens_trade(monkeypatch, fast_fills):
    _patch_snapshot(monkeypatch, entry_module, z=2.5)  # |Z| ≥ 1.5 → entry signal
    gate, client = _make_gate(auto=True)

    result, repo = await _run_entry(gate, client)

    assert result["opened"] == 1
    assert len(client.sent) == 1  # the operator was prompted
    open_trades = await repo.get_open_trades(exchange="dydx", mode="forward_test")
    assert len(open_trades) == 1


async def test_entry_rejected_skips_trade(monkeypatch, fast_fills):
    _patch_snapshot(monkeypatch, entry_module, z=2.5)
    gate, client = _make_gate(auto=False)

    result, repo = await _run_entry(gate, client)

    assert result["opened"] == 0
    assert result["outcomes"][0]["action"] == "rejected"
    assert await repo.get_open_trades(exchange="dydx", mode="forward_test") == []


async def test_entry_timeout_skips_trade(monkeypatch, fast_fills):
    _patch_snapshot(monkeypatch, entry_module, z=2.5)
    gate, client = _make_gate(auto=None, timeout_s=0.05)  # no tap → times out

    result, repo = await _run_entry(gate, client)

    assert result["opened"] == 0
    assert result["outcomes"][0]["action"] == "rejected"


# ── exit: approval gates the close too ───────────────────────────────────────


async def _open_then_exit(gate, client, *, exit_z: float):
    repo = FakeLiveRepository()
    await repo.start_session(exchange="dydx", mode="forward_test")
    session = await repo.get_active_session(exchange="dydx", mode="forward_test")
    trade_client = FakeTradeClient(prices={"AAA-USD": 100.0, "BBB-USD": 50.0})
    # Seed one OPEN trade with both legs live on the fake exchange.
    await repo.create_trade(
        {
            "session_id": session["id"],
            "exchange": "dydx",
            "mode": "forward_test",
            "status": "OPEN",
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "base_side": "BUY",
            "quote_side": "SELL",
            "base_size": 1.0,
            "quote_size": 2.0,
            "entry_price_leg1": 100.0,
            "entry_price_leg2": 50.0,
            "entry_z_score": 2.5,
            "hedge_ratio": 1.0,
            "half_life": 10.0,
            "opened_at": "2025-01-01T00:00:00+00:00",
        }
    )
    await trade_client.place_market_order(market="AAA-USD", side="BUY", size=1.0)
    await trade_client.place_market_order(market="BBB-USD", side="SELL", size=2.0)
    result = await manage_exits(
        trade_client=trade_client,
        data_client=object(),
        repo=repo,
        gate=gate,
        alerter=TelegramAlerter(client),
        exchange="dydx",
        mode="forward_test",
    )
    return result, repo, trade_client


async def test_exit_approved_closes(monkeypatch):
    _patch_snapshot(monkeypatch, exit_module, z=0.1)  # |Z| < 0.5 → take-profit exit
    gate, client = _make_gate(auto=True)

    result, repo, trade_client = await _open_then_exit(gate, client, exit_z=0.1)

    assert result["closed"] == 1
    assert len(client.sent) == 1
    assert "AAA-USD" not in trade_client.positions


async def test_exit_rejected_holds(monkeypatch):
    _patch_snapshot(monkeypatch, exit_module, z=0.1)
    gate, client = _make_gate(auto=False)

    result, repo, trade_client = await _open_then_exit(gate, client, exit_z=0.1)

    assert result["closed"] == 0
    assert result["outcomes"][0]["reason"] == "rejected"
    # Position untouched — the close was not approved.
    assert "AAA-USD" in trade_client.positions
