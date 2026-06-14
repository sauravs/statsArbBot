"""
Integration tests for the live trading HTTP surface (Phase 5a, PRD F5).

Real FastAPI app + mocked dYdX (FakeTradeClient) + in-memory repositories.
Exercises the gate's acceptance: session → entry opens a real-priced trade →
exit closes it with computed P&L → list reflects state; plus the collateral
guard, abort, no-session, and auth paths.

The current-price/Z snapshot is injected (``current_pair_snapshot`` is already
unit-tested in Phase 4); these tests own the *engine* — order execution, DB-backed
state, and P&L — so Z is scripted to drive deterministic entry/exit transitions.
"""

from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

import config
import db.live_repository as live_repo_module
import db.scan_repository as scan_repo_module
import trading.engine as engine_module
import trading.entry as entry_module
import trading.exit as exit_module
from app import create_app
from marketdata.pair_series import PairSnapshot
from tests.conftest import FakeLiveRepository, FakeScanRepository, FakeTradeClient

AUTH = {"X-API-Key": config.API_KEY}
PAIR = {
    "base_market": "AAA-USD",
    "quote_market": "BBB-USD",
    "hedge_ratio": 1.0,
    "intercept": 0.0,
    "half_life": 10.0,
    "zero_crossings": 5,
    "p_value": 0.01,
    "z_score": 2.0,
    "spread_std": 1.0,
}


@pytest.fixture
def ctx(monkeypatch):
    # Fresh repositories + engine (new asyncio lock per TestClient loop).
    scan_repo = FakeScanRepository()
    scan_repo.store[("dydx", "forward_test")] = [dict(PAIR)]
    live_repo = FakeLiveRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", scan_repo)
    monkeypatch.setattr(live_repo_module, "_repo", live_repo)
    monkeypatch.setattr(engine_module, "_engine", None)

    # Mocked dYdX trade client; offline data source for the (unused) data client.
    trade_client = FakeTradeClient(prices={"AAA-USD": 100.0, "BBB-USD": 50.0})

    async def _make_trade_client():
        return trade_client

    monkeypatch.setattr(engine_module, "make_trade_client", _make_trade_client)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    # Shrink fill polling so the entry path resolves instantly.
    monkeypatch.setattr(config, "MAX_ORDER_WAIT_SECS", 0.1)
    monkeypatch.setattr(config, "ORDER_POLL_INTERVAL", 0.01)

    # Scripted current price/Z snapshot, controllable per pass.
    snap_holder = {"value": None}

    async def _fake_snapshot(*_a, **_k):
        return snap_holder["value"]

    monkeypatch.setattr(entry_module, "current_pair_snapshot", _fake_snapshot)
    monkeypatch.setattr(exit_module, "current_pair_snapshot", _fake_snapshot)

    client = TestClient(create_app())
    return types.SimpleNamespace(
        client=client,
        trade_client=trade_client,
        scan_repo=scan_repo,
        live_repo=live_repo,
        snap_holder=snap_holder,
    )


def _set_snap(ctx, *, z, base=100.0, quote=50.0):
    ctx.snap_holder["value"] = PairSnapshot(
        base_price=base, quote_price=quote, spread_value=0.0, z_score=z
    )


# ── auth / validation ─────────────────────────────────────────────────────────


def test_endpoints_require_auth(ctx):
    assert ctx.client.post("/api/live/session/start", json={}).status_code == 401
    assert ctx.client.get("/api/live/trades").status_code == 401
    assert ctx.client.post("/api/live/entry-scan", json={}).status_code == 401


def test_invalid_mode_rejected(ctx):
    r = ctx.client.post("/api/live/session/start", json={"mode": "simulation"}, headers=AUTH)
    assert r.status_code == 422


def test_hyperliquid_live_rejected(ctx):
    # HL data is integrated, but it has no live_modes yet (trade client = Slice 4),
    # so a live start must be cleanly 422'd at the front door rather than reaching
    # make_trade_client (which raises NotImplementedError → 500).
    r = ctx.client.post(
        "/api/live/session/start",
        json={"exchange": "hyperliquid", "mode": "forward_test"},
        headers=AUTH,
    )
    assert r.status_code == 422
    assert "does not support live trading" in r.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"entry_threshold": 0},      # opens every pair (|Z| >= 0)
        {"entry_threshold": -1},
        {"entry_threshold": 5.0},    # above the documented Z range
        {"stop_threshold": 0},       # |Z| >= 0 always → force-closes the book
        {"stop_threshold": 0.5},     # below entry — nonsensical
        {"exit_threshold": 0},       # never takes profit
        {"exit_threshold": 3.0},
    ],
)
def test_out_of_range_threshold_overrides_rejected(ctx, body):
    # The trust boundary, not the UI clamp: a forged/curl request can't pass a
    # degenerate threshold even with a valid session key.
    r = ctx.client.post("/api/live/entry-scan", json=body, headers=AUTH)
    assert r.status_code == 422
    r = ctx.client.post("/api/live/exit-manage", json=body, headers=AUTH)
    assert r.status_code == 422


def test_in_range_threshold_overrides_accepted(ctx):
    # Boundary-valid overrides pass validation (no session → 409, not 422).
    r = ctx.client.post(
        "/api/live/entry-scan", json={"entry_threshold": 0.5}, headers=AUTH
    )
    assert r.status_code == 409  # validation passed; rejected only for no session


def test_entry_scan_without_session_409(ctx):
    _set_snap(ctx, z=2.5)
    r = ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH)
    assert r.status_code == 409


# ── session control ─────────────────────────────────────────────────────────


def test_session_start_stop(ctx):
    r = ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    assert r.status_code == 201
    assert r.json()["active"] is True

    s = ctx.client.get("/api/live/session", headers=AUTH).json()
    assert s["active"] is True

    stop = ctx.client.post("/api/live/session/stop", json={}, headers=AUTH).json()
    assert stop["stopped_sessions"] == 1
    assert ctx.client.get("/api/live/session", headers=AUTH).json()["active"] is False


# ── full lifecycle ────────────────────────────────────────────────────────────


def test_full_entry_exit_pnl_lifecycle(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)

    # Entry: |Z|=2.5 ≥ 1.5 → SELL base / BUY quote (z>0). Both legs fill.
    _set_snap(ctx, z=2.5, base=100.0, quote=50.0)
    r = ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["opened"] == 1 and body["collateral_ok"] is True

    open_trades = ctx.client.get(
        "/api/live/trades", params={"status": "OPEN"}, headers=AUTH
    ).json()["trades"]
    assert len(open_trades) == 1
    t = open_trades[0]
    assert t["base_side"] == "SELL" and t["quote_side"] == "BUY"
    assert t["entry_price_leg1"] == 100.0 and t["entry_price_leg2"] == 50.0
    assert t["base_size"] == pytest.approx(1.0) and t["quote_size"] == pytest.approx(2.0)
    assert set(ctx.trade_client.positions) == {"AAA-USD", "BBB-USD"}

    # Exit: |Z|=0.1 < 0.5 → TAKE_PROFIT. Close fills at new prices.
    _set_snap(ctx, z=0.1)
    ctx.trade_client.prices = {"AAA-USD": 90.0, "BBB-USD": 55.0}
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["closed"] == 1
    assert ctx.trade_client.positions == {}  # both legs unwound

    closed = ctx.client.get(
        "/api/live/trades", params={"status": "CLOSED"}, headers=AUTH
    ).json()["trades"]
    assert len(closed) == 1
    c = closed[0]
    assert c["exit_reason"] == "TAKE_PROFIT"
    # base SELL(short) 1u 100→90 = +10 ; quote BUY(long) 2u 50→55 = +10.
    assert c["pnl"] == pytest.approx(20.0)
    assert c["exit_price_leg1"] == 90.0 and c["exit_price_leg2"] == 55.0


def test_stop_loss_exit_on_divergence(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    _set_snap(ctx, z=2.0)
    ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH)

    # |Z| = 4.5 ≥ 4.0 → STOP_LOSS_ZSCORE.
    _set_snap(ctx, z=4.5)
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH)
    assert r.json()["closed"] == 1
    closed = ctx.client.get(
        "/api/live/trades", params={"status": "CLOSED"}, headers=AUTH
    ).json()["trades"]
    assert closed[0]["exit_reason"] == "STOP_LOSS_ZSCORE"


def test_exit_holds_when_signal_absent(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    _set_snap(ctx, z=2.0)
    ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH)

    # |Z| = 1.0 → between exit (0.5) and stop (4.0): hold.
    _set_snap(ctx, z=1.0)
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH)
    assert r.json()["closed"] == 0
    assert len(ctx.client.get("/api/live/trades", params={"status": "OPEN"}, headers=AUTH).json()["trades"]) == 1


# ── guards & safety ────────────────────────────────────────────────────────────


def test_collateral_guard_blocks_entry(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    ctx.trade_client.free_collateral = 100.0  # below USD_MIN_COLLATERAL (1880)
    _set_snap(ctx, z=2.5)
    r = ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH).json()
    assert r["opened"] == 0 and r["collateral_ok"] is False
    assert ctx.trade_client.positions == {}


def test_no_double_open_same_pair(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    _set_snap(ctx, z=2.5)
    assert ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH).json()["opened"] == 1
    # Second pass: the pair is already OPEN → skipped, not reopened.
    assert ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH).json()["opened"] == 0


def _open_one(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    _set_snap(ctx, z=2.5)
    assert ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH).json()["opened"] == 1


def test_reconcile_both_legs_gone_records_unknown_pnl(ctx):
    _open_one(ctx)
    # Both legs closed outside the bot.
    ctx.trade_client.positions = {}
    _set_snap(ctx, z=1.0)
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH).json()
    assert r["closed"] == 1
    c = ctx.client.get("/api/live/trades", params={"status": "CLOSED"}, headers=AUTH).json()["trades"][0]
    assert c["exit_reason"] == "RECONCILED"
    # Fills unknown → P&L not fabricated.
    assert c["pnl"] is None
    assert c["exit_price_leg1"] is None and c["exit_price_leg2"] is None


def test_orphan_leg_is_closed_and_reconciled(ctx):
    _open_one(ctx)
    # Quote leg vanished; base leg still live → orphan.
    ctx.trade_client.positions.pop("BBB-USD")
    _set_snap(ctx, z=1.0)
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH).json()
    assert r["closed"] == 1
    assert ctx.trade_client.positions == {}  # orphan base leg unwound
    c = ctx.client.get("/api/live/trades", params={"status": "CLOSED"}, headers=AUTH).json()["trades"][0]
    assert c["exit_reason"] == "ORPHANED"
    assert c["pnl"] is None


def test_orphan_close_failure_keeps_open_and_alerts(ctx, monkeypatch):
    import trading.alerts as alerts_mod

    class RecordingAlerter:
        def __init__(self):
            self.code_reds = []

        async def notify(self, m):
            pass

        async def code_red(self, m):
            self.code_reds.append(m)

    recorder = RecordingAlerter()
    monkeypatch.setattr(alerts_mod, "_alerter", recorder)

    _open_one(ctx)
    ctx.trade_client.positions.pop("BBB-USD")  # orphan: base still live
    ctx.trade_client.fail_close_markets = {"AAA-USD"}  # its close will fail
    _set_snap(ctx, z=1.0)
    r = ctx.client.post("/api/live/exit-manage", json={}, headers=AUTH).json()
    assert r["closed"] == 0  # not closed — the naked leg could not be unwound
    # Trade stays OPEN for the next pass to retry, and CODE RED fired.
    assert len(ctx.client.get("/api/live/trades", params={"status": "OPEN"}, headers=AUTH).json()["trades"]) == 1
    assert len(recorder.code_reds) == 1


def test_abort_closes_positions_and_marks_trades(ctx):
    ctx.client.post("/api/live/session/start", json={}, headers=AUTH)
    _set_snap(ctx, z=2.5)
    ctx.client.post("/api/live/entry-scan", json={}, headers=AUTH)
    assert ctx.trade_client.positions != {}

    r = ctx.client.post("/api/live/abort", json={}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trades_marked"] == 1
    assert all(p["ok"] for p in body["positions_closed"])
    assert ctx.trade_client.positions == {}
    assert ctx.trade_client.cancelled is True
    # The OPEN trade is now CLOSED (ABORTED).
    assert len(ctx.client.get("/api/live/trades", params={"status": "OPEN"}, headers=AUTH).json()["trades"]) == 0
    closed = ctx.client.get("/api/live/trades", params={"status": "CLOSED"}, headers=AUTH).json()["trades"]
    assert closed[0]["exit_reason"] == "ABORTED"
