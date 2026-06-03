"""
Unit tests for the Telegram approval gate + alerter (Phase 9.0, PRD F9.1).

Mocked Telegram: a ``FakeBotClient`` records sent prompts/edits and resolves the
gate's pending future on demand — so approve / reject / timeout are driven
entirely in-process with no ``python-telegram-bot`` installed.
"""

from __future__ import annotations

import asyncio

import pytest

from telegrambot.alerter import TelegramAlerter
from telegrambot.gate import TelegramApprovalGate, _format_signal

ENTRY_SIGNAL = {
    "kind": "entry",
    "base_market": "AAA-USD",
    "quote_market": "BBB-USD",
    "base_side": "BUY",
    "quote_side": "SELL",
    "z_score": -2.34,
}


class FakeBotClient:
    """In-memory BotClient. ``auto`` (None/True/False) simulates an instant tap."""

    def __init__(self, *, auto: bool | None = None, fail_send: bool = False) -> None:
        self.gate: TelegramApprovalGate | None = None
        self.auto = auto
        self.fail_send = fail_send
        self.sent: list[tuple[str, str, int]] = []  # (text, token, message_id)
        self.edits: list[tuple[int, str]] = []
        self.plain: list[str] = []
        self._next_id = 1
        self.raise_on_send = False

    async def send_approval_request(self, *, text, approve_data, reject_data):
        if self.fail_send:
            return None
        token = approve_data.split(":", 1)[1]
        mid = self._next_id
        self._next_id += 1
        self.sent.append((text, token, mid))
        if self.auto is not None and self.gate is not None:
            self.gate.resolve(token, self.auto)
        return mid

    async def edit_message(self, *, message_id, text):
        self.edits.append((message_id, text))

    async def send_message(self, *, text):
        if self.raise_on_send:
            raise RuntimeError("network down")
        self.plain.append(text)


def _gate(client: FakeBotClient, *, timeout_s: float = 5.0) -> TelegramApprovalGate:
    gate = TelegramApprovalGate(client, timeout_s=timeout_s)
    client.gate = gate
    return gate


# ── approve / reject (operator taps a button) ────────────────────────────────


async def test_approve_returns_true_and_edits_message():
    client = FakeBotClient()
    gate = _gate(client)

    task = asyncio.create_task(gate.request(ENTRY_SIGNAL))
    await asyncio.sleep(0.01)  # let request send the prompt + register the future
    assert len(client.sent) == 1
    token = client.sent[0][1]

    assert gate.resolve(token, True) is True
    assert await task is True
    # The prompt message was edited to record the decision.
    assert client.edits and "Approved" in client.edits[-1][1]


async def test_reject_returns_false():
    client = FakeBotClient()
    gate = _gate(client)

    task = asyncio.create_task(gate.request(ENTRY_SIGNAL))
    await asyncio.sleep(0.01)
    token = client.sent[0][1]
    gate.resolve(token, False)

    assert await task is False
    assert "Rejected" in client.edits[-1][1]


# ── timeout (no tap) ─────────────────────────────────────────────────────────


async def test_timeout_auto_rejects():
    client = FakeBotClient()
    gate = _gate(client, timeout_s=0.05)

    result = await gate.request(ENTRY_SIGNAL)

    assert result is False
    assert "Timed out" in client.edits[-1][1]


async def test_zero_timeout_is_kill_switch_no_prompt():
    client = FakeBotClient()
    gate = _gate(client, timeout_s=0.0)

    result = await gate.request(ENTRY_SIGNAL)

    assert result is False
    assert client.sent == []  # never prompted the operator


# ── failed send fails safe (skip, don't block for the full timeout) ──────────


async def test_failed_send_returns_false_immediately():
    client = FakeBotClient(fail_send=True)
    gate = _gate(client, timeout_s=10.0)

    # If this blocked on the timeout the test would hang; wait_for guards that.
    result = await asyncio.wait_for(gate.request(ENTRY_SIGNAL), timeout=1.0)

    assert result is False


# ── auto-resolve path (the integration fakes use this) + cleanup ─────────────


async def test_auto_decision_resolves_synchronously():
    client = FakeBotClient(auto=True)
    gate = _gate(client)

    assert await gate.request(ENTRY_SIGNAL) is True
    # No pending futures leak after a decision.
    assert gate._pending == {}


async def test_stale_token_resolution_is_ignored():
    client = FakeBotClient()
    gate = _gate(client)
    # Resolving an unknown token must not raise and reports no match.
    assert gate.resolve("nope", True) is False


# ── callback_data parsing ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "data,expected",
    [
        ("approve:abc123", ("abc123", True)),
        ("reject:abc123", ("abc123", False)),
        ("other:abc123", None),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse_callback(data, expected):
    assert TelegramApprovalGate.parse_callback(data) == expected


# ── prompt formatting ────────────────────────────────────────────────────────


def test_format_signal_includes_pair_z_sides_and_reason():
    text = _format_signal({**ENTRY_SIGNAL, "reason": "TAKE_PROFIT"})
    assert "AAA-USD / BBB-USD" in text
    assert "-2.34" in text
    assert "AAA-USD BUY" in text and "BBB-USD SELL" in text
    assert "TAKE_PROFIT" in text


def test_format_signal_tolerates_missing_z():
    text = _format_signal({"kind": "exit", "base_market": "A", "quote_market": "B"})
    assert "n/a" in text


# ── alerter ──────────────────────────────────────────────────────────────────


async def test_alerter_notify_and_code_red_post_messages():
    client = FakeBotClient()
    alerter = TelegramAlerter(client)

    await alerter.notify("trade opened")
    await alerter.code_red("naked leg")

    assert any("trade opened" in m for m in client.plain)
    assert any("CODE RED" in m and "naked leg" in m for m in client.plain)


async def test_alerter_never_raises_when_send_fails():
    client = FakeBotClient()
    client.raise_on_send = True
    alerter = TelegramAlerter(client)

    # Contract: an Alerter must never raise (the engine's CODE-RED path relies on
    # it). Even with a client that raises on every send, both methods must return
    # cleanly rather than propagate.
    await alerter.notify("x")
    await alerter.code_red("y")
