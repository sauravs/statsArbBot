"""
Unit tests for the atomic two-leg executor (Phase 5a, trading/bot_agent.py).

Focus: the safety-critical failsafe path — a filled leg 1 must never be left naked
when leg 2 fails, and an un-closable leg 1 must raise CODE RED.
"""

from __future__ import annotations

import pytest

from tests.conftest import FakeTradeClient
from trading.bot_agent import BotAgent

pytestmark = pytest.mark.asyncio


class RecordingAlerter:
    def __init__(self) -> None:
        self.notices: list[str] = []
        self.code_reds: list[str] = []

    async def notify(self, message: str) -> None:
        self.notices.append(message)

    async def code_red(self, message: str) -> None:
        self.code_reds.append(message)


def _agent(client, alerter, **over):
    kwargs = dict(
        base_market="AAA-USD",
        quote_market="BBB-USD",
        base_side="BUY",
        quote_side="SELL",
        base_size=1.0,
        quote_size=2.0,
        entry_z_score=-2.0,
        hedge_ratio=1.0,
        half_life=10.0,
        max_wait_secs=0.05,
        poll_interval=0.01,
    )
    kwargs.update(over)
    return BotAgent(client, alerter, **kwargs)


async def test_both_legs_fill_is_live():
    client = FakeTradeClient(prices={"AAA-USD": 100.0, "BBB-USD": 50.0})
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "LIVE"
    assert agent.status == "LIVE"
    assert set(client.positions) == {"AAA-USD", "BBB-USD"}
    snap = agent.entry_snapshot()
    assert snap["entry_price_leg1"] == 100.0 and snap["entry_price_leg2"] == 50.0
    assert alerter.code_reds == []
    assert any("opened" in n for n in alerter.notices)


async def test_leg1_submission_failure_aborts_no_failsafe():
    client = FakeTradeClient(prices={"AAA-USD": 100.0}, fail_open_markets={"AAA-USD"})
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "ERROR"
    assert client.positions == {}  # nothing opened
    assert client.orders == []  # leg 1 never accepted
    assert alerter.code_reds == []


async def test_leg2_failure_triggers_failsafe_close():
    client = FakeTradeClient(
        prices={"AAA-USD": 100.0, "BBB-USD": 50.0}, fail_open_markets={"BBB-USD"}
    )
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "ERROR"
    # Leg 1 was opened then failsafe-closed → no naked position remains.
    assert "AAA-USD" not in client.positions
    assert any(o["reduce_only"] and o["market"] == "AAA-USD" for o in client.orders)
    assert alerter.code_reds == []  # failsafe succeeded


async def test_leg2_fill_timeout_triggers_failsafe():
    client = FakeTradeClient(
        prices={"AAA-USD": 100.0, "BBB-USD": 50.0}, no_fill_markets={"BBB-USD"}
    )
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "ERROR"
    assert "AAA-USD" not in client.positions
    assert alerter.code_reds == []


async def test_failsafe_failure_raises_code_red():
    # Leg 2 submission fails AND the leg-1 failsafe close also fails → CODE RED.
    client = FakeTradeClient(
        prices={"AAA-USD": 100.0, "BBB-USD": 50.0},
        fail_open_markets={"BBB-USD"},
        fail_close_markets={"AAA-USD"},
    )
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "ERROR"
    # The failsafe close failed, so leg 1 is left naked — exactly the case CODE RED
    # exists for; the alarm must fire once and name the stuck market.
    assert set(client.positions) == {"AAA-USD"}
    assert len(alerter.code_reds) == 1
    assert "AAA-USD" in alerter.code_reds[0]


async def test_leg1_fill_timeout_aborts():
    client = FakeTradeClient(prices={"AAA-USD": 100.0}, no_fill_markets={"AAA-USD"})
    alerter = RecordingAlerter()
    agent = _agent(client, alerter)

    assert await agent.open_trades() == "ERROR"
    assert client.positions == {}
    assert alerter.code_reds == []
