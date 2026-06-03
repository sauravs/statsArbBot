"""
Integration tests for the simulation HTTP surface (Phase 6, PRD F6.5).

Real FastAPI app + in-memory ``FakeSimRepository`` + scripted snapshots. Exercises
the gate's acceptance — create a session → tick → a virtual trade opens on a real
signal → positions/PnL update — plus pause/resume/stop/topup lifecycle, validation,
and auth. The scheduler is stubbed (no real APScheduler jobs fire during tests); the
``/tick`` endpoint drives ticks deterministically.
"""

from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

import config
import db.sim_repository as sim_repo_module
import routers.sim as sim_router_module
import simulation.engine as engine_module
from app import create_app
from simulation.feed import PairTick
from tests.conftest import FakeSimRepository

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def ctx(monkeypatch):
    repo = FakeSimRepository()
    monkeypatch.setattr(sim_repo_module, "_repo", repo)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")

    # Stub the scheduler so create/resume/pause/stop don't touch APScheduler.
    sched = types.SimpleNamespace(
        scheduled=set(),
        schedule=lambda sid, secs: sched.scheduled.add(sid),
        unschedule=lambda sid: sched.scheduled.discard(sid),
        available=True,
    )
    monkeypatch.setattr(sim_router_module, "sim_scheduler", sched)

    # Scripted snapshots: the engine builds these from the live feed in production;
    # here a holder lets each test drive deterministic entry/exit transitions.
    snap_holder: dict = {"value": []}

    async def _fake_snapshots(self, session, only_pairs=None):
        snaps = list(snap_holder["value"])
        if only_pairs is not None:
            snaps = [s for s in snaps if (s.base_market, s.quote_market) in only_pairs]
        return snaps

    monkeypatch.setattr(engine_module.SimulationEngine, "_snapshots_for", _fake_snapshots)

    client = TestClient(create_app())
    return types.SimpleNamespace(client=client, repo=repo, snaps=snap_holder, sched=sched)


def _set_snaps(ctx, *snaps: PairTick) -> None:
    ctx.snaps["value"] = list(snaps)


def _snap(z, base="DEMO3-USD", quote="DEMO4-USD", base_price=100.0, quote_price=50.0):
    return PairTick(
        base_market=base, quote_market=quote, hedge_ratio=2.0, half_life=10.0,
        base_price=base_price, quote_price=quote_price, z_score=z, spread_value=0.0,
    )


def _create(ctx, **body) -> dict:
    payload = {"starting_capital": 10_000.0, "interval_seconds": 60,
               "slippage_pct": 0.0, "taker_fee_pct": 0.0}
    payload.update(body)
    r = ctx.client.post("/api/sim/sessions", json=payload, headers=AUTH)
    assert r.status_code == 201, r.text
    return r.json()


# ── auth / validation ────────────────────────────────────────────────────────


def test_endpoints_require_auth(ctx):
    assert ctx.client.get("/api/sim/sessions").status_code == 401
    assert ctx.client.post("/api/sim/sessions", json={}).status_code == 401


@pytest.mark.parametrize("body", [
    {"starting_capital": 0},
    {"starting_capital": -100},
    {"entry_threshold": 0},      # |Z|≥0 opens everything
    {"entry_threshold": 5.0},
    {"stop_threshold": 0.5},     # below the documented stop range
    {"interval_seconds": 0},
    {"exit_threshold": 0},
])
def test_invalid_create_body_rejected(ctx, body):
    payload = {"starting_capital": 10_000.0, **body}
    assert ctx.client.post("/api/sim/sessions", json=payload, headers=AUTH).status_code == 422


def test_unknown_exchange_rejected(ctx):
    r = ctx.client.post("/api/sim/sessions",
                        json={"exchange": "ftx", "starting_capital": 100.0}, headers=AUTH)
    assert r.status_code == 422


def test_get_missing_session_404(ctx):
    assert ctx.client.get("/api/sim/sessions/nope", headers=AUTH).status_code == 404
    assert ctx.client.post("/api/sim/sessions/nope/tick", headers=AUTH).status_code == 404


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_create_lists_and_schedules(ctx):
    s = _create(ctx, label="My sim")
    assert s["status"] == "RUNNING" and s["current_capital"] == 10_000.0
    assert s["id"] in ctx.sched.scheduled
    listed = ctx.client.get("/api/sim/sessions", headers=AUTH).json()
    assert listed["count"] == 1 and listed["sessions"][0]["label"] == "My sim"


def test_pause_resume_stop_transitions(ctx):
    s = _create(ctx)
    sid = s["id"]
    assert ctx.client.post(f"/api/sim/sessions/{sid}/pause", headers=AUTH).json()["status"] == "PAUSED"
    assert sid not in ctx.sched.scheduled
    assert ctx.client.post(f"/api/sim/sessions/{sid}/resume", headers=AUTH).json()["status"] == "RUNNING"
    assert sid in ctx.sched.scheduled
    assert ctx.client.post(f"/api/sim/sessions/{sid}/stop", headers=AUTH).json()["session"]["status"] == "STOPPED"
    assert sid not in ctx.sched.scheduled
    # A stopped session can't resume.
    assert ctx.client.post(f"/api/sim/sessions/{sid}/resume", headers=AUTH).status_code == 409


def test_stopped_session_is_terminal(ctx):
    # STOPPED is terminal: pause must not launder it to PAUSED (which would let
    # resume revive it), and topup must not touch a dead session — all 409.
    s = _create(ctx)
    sid = s["id"]
    ctx.client.post(f"/api/sim/sessions/{sid}/stop", headers=AUTH)
    assert ctx.client.post(f"/api/sim/sessions/{sid}/pause", headers=AUTH).status_code == 409
    assert ctx.client.post(f"/api/sim/sessions/{sid}/resume", headers=AUTH).status_code == 409
    assert ctx.client.post(f"/api/sim/sessions/{sid}/topup", json={"amount": 100.0}, headers=AUTH).status_code == 409
    # Still STOPPED, never re-scheduled.
    assert ctx.client.get(f"/api/sim/sessions/{sid}", headers=AUTH).json()["session"]["status"] == "STOPPED"
    assert sid not in ctx.sched.scheduled


def test_list_realised_pnl_excludes_topups(ctx):
    # Top-up inflates capital but is not profit — the list's realised P&L (Σ closed
    # net_pnl) stays 0 with no trades, even though current_capital rose.
    s = _create(ctx, starting_capital=10_000.0)
    ctx.client.post(f"/api/sim/sessions/{s['id']}/topup", json={"amount": 5_000.0}, headers=AUTH)
    row = ctx.client.get("/api/sim/sessions", headers=AUTH).json()["sessions"][0]
    assert row["current_capital"] == pytest.approx(15_000.0)
    assert row["realised_pnl"] == pytest.approx(0.0)


def test_synthetic_stop_charges_no_exit_slippage_or_fee(ctx):
    # Stop with no live price closes flat at entry prices and must NOT charge exit
    # slippage/fees on a fill that never happened — only the already-paid entry fee
    # is realised. With 0.05% costs the entry fee is ~0.10; a buggy synthetic close
    # would deduct ~0.30.
    s = _create(ctx, slippage_pct=0.05, taker_fee_pct=0.05)
    sid = s["id"]
    _set_snaps(ctx, _snap(z=2.5, base_price=100.0, quote_price=50.0))
    ctx.client.post(f"/api/sim/sessions/{sid}/tick", headers=AUTH)
    _set_snaps(ctx)  # no live price for the open pair on stop → synthetic close
    ctx.client.post(f"/api/sim/sessions/{sid}/stop", headers=AUTH)
    trade = ctx.client.get(f"/api/sim/sessions/{sid}", headers=AUTH).json()["trades"][0]
    assert trade["net_pnl"] == pytest.approx(-0.10, abs=0.02)


def test_topup_increases_capital(ctx):
    s = _create(ctx, starting_capital=1_000.0)
    r = ctx.client.post(f"/api/sim/sessions/{s['id']}/topup", json={"amount": 500.0}, headers=AUTH)
    assert r.json()["current_capital"] == pytest.approx(1_500.0)
    assert ctx.client.post(f"/api/sim/sessions/{s['id']}/topup",
                           json={"amount": -5.0}, headers=AUTH).status_code == 422


def test_paused_session_tick_is_skipped(ctx):
    s = _create(ctx)
    ctx.client.post(f"/api/sim/sessions/{s['id']}/pause", headers=AUTH)
    _set_snaps(ctx, _snap(z=2.5))
    r = ctx.client.post(f"/api/sim/sessions/{s['id']}/tick", headers=AUTH).json()
    assert r.get("skipped") is True


# ── acceptance: tick opens/closes virtual trades on real signals ─────────────


def test_tick_opens_virtual_trade_and_updates_overview(ctx):
    s = _create(ctx)
    sid = s["id"]
    _set_snaps(ctx, _snap(z=2.5))  # |Z|≥1.5 → open
    r = ctx.client.post(f"/api/sim/sessions/{sid}/tick", headers=AUTH).json()
    assert r["entries"] == 1 and r["exits"] == 0

    ov = ctx.client.get(f"/api/sim/sessions/{sid}", headers=AUTH).json()
    assert ov["open_count"] == 1
    pos = ov["positions"][0]
    assert pos["direction"] == "SHORT_BASE"
    assert pos["unrealized_pnl"] is not None  # marked to market from the snapshot
    assert ov["session"]["tick_count"] == 1


def test_full_open_then_close_pnl_lifecycle(ctx):
    s = _create(ctx)
    sid = s["id"]
    # Open on a strong signal.
    _set_snaps(ctx, _snap(z=2.5, base_price=100.0, quote_price=50.0))
    assert ctx.client.post(f"/api/sim/sessions/{sid}/tick", headers=AUTH).json()["entries"] == 1
    # Revert below exit threshold with a profitable price move.
    _set_snaps(ctx, _snap(z=0.1, base_price=90.0, quote_price=55.0))
    assert ctx.client.post(f"/api/sim/sessions/{sid}/tick", headers=AUTH).json()["exits"] == 1

    ov = ctx.client.get(f"/api/sim/sessions/{sid}", headers=AUTH).json()
    assert ov["open_count"] == 0 and ov["closed_count"] == 1
    trade = ov["trades"][0]
    assert trade["exit_reason"] == "TAKE_PROFIT"
    assert trade["net_pnl"] == pytest.approx(20.0)
    # Capital reflects realised P&L (only changes on close).
    assert ov["session"]["current_capital"] == pytest.approx(10_020.0)


def test_stop_force_closes_open_positions(ctx):
    s = _create(ctx)
    sid = s["id"]
    _set_snaps(ctx, _snap(z=2.5))
    ctx.client.post(f"/api/sim/sessions/{sid}/tick", headers=AUTH)
    r = ctx.client.post(f"/api/sim/sessions/{sid}/stop", headers=AUTH).json()
    assert r["positions_closed"] == 1
    ov = ctx.client.get(f"/api/sim/sessions/{sid}", headers=AUTH).json()
    assert ov["open_count"] == 0 and ov["closed_count"] == 1
    assert ov["trades"][0]["exit_reason"] == "STOPPED"
