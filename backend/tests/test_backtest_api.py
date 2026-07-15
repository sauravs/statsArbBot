"""
Integration tests for the backtest HTTP surface (Phase 8, PRD F8.3/F8.4).

Real FastAPI app + in-memory ``FakeStrategyRepository`` + an injected demo candle
source. Under Starlette's TestClient a ``BackgroundTasks`` job runs to completion
before the POST response is delivered, so the run → GET-detail flow deterministically
observes a COMPLETED backtest with its aggregates + report. Also covers CRUD,
ranking, validation, the report endpoint, seed-defaults, 404s, and auth.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
import backtest.engine as engine_module
import db.backtest_repository as repo_module
from app import create_app
from tests.conftest import FakeStrategyRepository

AUTH = {"X-API-Key": config.API_KEY}
_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
_N = 420


class FakeCandleSource:
    def __init__(self, candles):
        self._candles = candles

    async def get_candles(self, market, *, start, end):
        return [c for c in self._candles.get(market, []) if start <= c["timestamp"] <= end]

    async def get_funding(self, market, *, start, end):
        return []

    async def available_markets(self):
        return sorted(self._candles.keys())


def _series():
    rng = np.random.default_rng(11)
    s2 = 100 + np.cumsum(rng.normal(0, 1, _N))
    eps = np.zeros(_N)
    for t in range(1, _N):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.6)
    s1 = 2.0 * s2 + 5.0 + eps
    return {
        m: [{"timestamp": _ANCHOR + timedelta(hours=i), "close": float(c)} for i, c in enumerate(s)]
        for m, s in (("AAA-USD", s1), ("BBB-USD", s2))
    }


@pytest.fixture
def ctx(monkeypatch):
    repo = FakeStrategyRepository()
    monkeypatch.setattr(repo_module, "_repo", repo)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    monkeypatch.setattr(engine_module, "make_candle_source", lambda **_: FakeCandleSource(_series()))
    client = TestClient(create_app())
    return types.SimpleNamespace(client=client, repo=repo)


_CREATE = {
    "name": "S1", "description": "baseline",
    "scan_window_days": 7, "trade_window_days": 3,
    "zscore_window": 21, "entry_threshold": 0.5,
    "start_time": _ANCHOR.isoformat(),
    "end_time": (_ANCHOR + timedelta(hours=_N - 1)).isoformat(),
    "slippage_pct": 0.0, "taker_fee_pct": 0.0,
}


# ── auth / validation ────────────────────────────────────────────────────────


def test_endpoints_require_auth(ctx):
    assert ctx.client.get("/api/backtest/strategies").status_code == 401
    assert ctx.client.post("/api/backtest/strategies", json={}).status_code == 401


@pytest.mark.parametrize("body", [
    {"name": ""},                              # empty name
    {"entry_threshold": 0.1},                  # below 0.5
    {"stop_threshold": 0.0},                   # below 1.0
    {"scan_window_days": 0},                   # below 1
    {"starting_capital": 0},                   # not > 0
    {"start_time": (_ANCHOR + timedelta(days=5)).isoformat(),
     "end_time": _ANCHOR.isoformat()},         # start >= end
])
def test_validation_rejects_bad_params(ctx, body):
    payload = {**_CREATE, **body}
    r = ctx.client.post("/api/backtest/strategies", json=payload, headers=AUTH)
    assert r.status_code == 422, r.text


# ── CRUD ─────────────────────────────────────────────────────────────────────


def test_crud_lifecycle(ctx):
    # Create.
    r = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "PENDING"

    # List.
    lst = ctx.client.get("/api/backtest/strategies", headers=AUTH).json()
    assert lst["count"] == 1

    # Get.
    got = ctx.client.get(f"/api/backtest/strategies/{sid}", headers=AUTH)
    assert got.status_code == 200
    assert got.json()["name"] == "S1"

    # Update.
    upd = ctx.client.put(
        f"/api/backtest/strategies/{sid}",
        json={"name": "S1-edited", "entry_threshold": 1.0},
        headers=AUTH,
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "S1-edited"
    assert upd.json()["entry_threshold"] == 1.0

    # Delete.
    dele = ctx.client.delete(f"/api/backtest/strategies/{sid}", headers=AUTH)
    assert dele.status_code == 200
    assert ctx.client.get(f"/api/backtest/strategies/{sid}", headers=AUTH).status_code == 404


async def test_cannot_edit_paused_strategy(ctx):
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    # A mid-sweep (PAUSED) strategy must not be editable — it would desync the resume.
    await ctx.repo.update(sid, {"status": "PAUSED", "processed_windows": 1, "total_windows": 3})
    r = ctx.client.put(f"/api/backtest/strategies/{sid}", json={"scan_window_days": 180}, headers=AUTH)
    assert r.status_code == 409, r.text


def test_partial_span_edit_validated_against_stored(ctx):
    # _CREATE has start < end. Editing ONLY start_time to after the stored end_time
    # must be rejected (effective-span check), not silently persisted.
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    later = (_ANCHOR + timedelta(hours=_N + 100)).isoformat()
    r = ctx.client.put(f"/api/backtest/strategies/{sid}", json={"start_time": later}, headers=AUTH)
    assert r.status_code == 422, r.text


def test_get_update_delete_404(ctx):
    assert ctx.client.get("/api/backtest/strategies/nope", headers=AUTH).status_code == 404
    assert ctx.client.put("/api/backtest/strategies/nope", json={"name": "x"}, headers=AUTH).status_code == 404
    assert ctx.client.delete("/api/backtest/strategies/nope", headers=AUTH).status_code == 404
    assert ctx.client.post("/api/backtest/strategies/nope/run", headers=AUTH).status_code == 404
    assert ctx.client.post("/api/backtest/strategies/nope/pause", headers=AUTH).status_code == 404
    assert ctx.client.post("/api/backtest/strategies/nope/stop", headers=AUTH).status_code == 404


# ── run lifecycle ────────────────────────────────────────────────────────────


def test_run_completes_and_reports(ctx):
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    # The background sweep completes before the POST returns (TestClient).
    run = ctx.client.post(f"/api/backtest/strategies/{sid}/run", headers=AUTH)
    assert run.status_code == 200
    assert run.json()["status"] == "RUNNING"  # snapshot at launch

    detail = ctx.client.get(f"/api/backtest/strategies/{sid}", headers=AUTH).json()
    assert detail["status"] == "COMPLETED"
    assert detail["total_trades"] > 0
    assert detail["progress"] == 1.0
    assert detail["equity_curve"]
    assert "AAA-USD/BBB-USD" in detail["per_pair_pnl"]
    assert detail["rank"] == 1

    # Report endpoint returns the generated markdown.
    rep = ctx.client.get(f"/api/backtest/strategies/{sid}/report", headers=AUTH).json()
    assert rep["report_md"] and "Backtest Report" in rep["report_md"]


def test_trades_endpoint_blotter(ctx):
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    ctx.client.post(f"/api/backtest/strategies/{sid}/run", headers=AUTH)
    detail = ctx.client.get(f"/api/backtest/strategies/{sid}", headers=AUTH).json()

    # Full blotter: total matches the aggregate, rows carry Z + prices + rationale.
    page = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?limit=500", headers=AUTH
    ).json()
    assert page["total"] == detail["total_trades"]
    assert len(page["trades"]) == detail["total_trades"]
    t0 = page["trades"][0]
    for k in ("window_index", "entry_time", "exit_time", "entry_z",
              "exit_reason", "entry_base_px", "exit_base_px", "net_pnl"):
        assert k in t0

    # Window scoping matches the per-window counts.
    w0 = detail["per_window"][0]
    scoped = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?window={w0['index']}&limit=500",
        headers=AUTH,
    ).json()
    assert scoped["total"] == w0["trades"]

    # Pagination.
    p = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?limit=1&offset=0", headers=AUTH
    ).json()
    assert len(p["trades"]) == 1 and p["limit"] == 1


def test_trade_series_chart(ctx, monkeypatch):
    # The per-trade chart builder fetches candles via its own make_candle_source.
    import backtest.trade_series as ts_mod
    monkeypatch.setattr(ts_mod, "make_candle_source", lambda **_: FakeCandleSource(_series()))

    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    ctx.client.post(f"/api/backtest/strategies/{sid}/run", headers=AUTH)
    trades = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?limit=1", headers=AUTH
    ).json()["trades"]
    assert trades
    tid = trades[0]["id"]

    r = ctx.client.get(f"/api/backtest/strategies/{sid}/trades/{tid}/series", headers=AUTH)
    assert r.status_code == 200, r.text
    d = r.json()
    # β/α were persisted this run → faithful spread/z, all four panels present.
    assert d["faithful"] is True
    s = d["series"]
    assert s["normalized"]["base"] and s["raw"]["base"]
    assert s["spread"]["series"] and s["zscore"]["series"]
    # The trade's own entry/exit overlays (with spread computed from β/α).
    assert d["entry"]["time"] and d["entry"]["z"] is not None
    assert d["exit"]["time"] and d["exit"]["spread"] is not None
    assert d["base_market"] == "AAA-USD" and d["quote_market"] == "BBB-USD"

    # Unknown trade → 404.
    assert (
        ctx.client.get(
            f"/api/backtest/strategies/{sid}/trades/nope/series", headers=AUTH
        ).status_code
        == 404
    )

    # The chart payload carries the P&L decomposition so the UI can explain a
    # losing take-profit: net = gross − fees + funding.
    for k in ("gross_pnl", "fee_cost", "funding_pnl", "net_pnl"):
        assert k in d, k
    assert abs((d["gross_pnl"] - d["fee_cost"] + d["funding_pnl"]) - d["net_pnl"]) < 1e-6


def test_trades_filter_losing_take_profit(ctx):
    """The ``losing_tp`` outcome filter returns exactly the take-profit exits that
    still closed at a net loss — filtered server-side so total/pagination are right."""
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    ctx.client.post(f"/api/backtest/strategies/{sid}/run", headers=AUTH)

    full = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?limit=500", headers=AUTH
    ).json()["trades"]
    expected = [
        t for t in full if t["exit_reason"] == "TAKE_PROFIT" and t["net_pnl"] < 0
    ]

    filtered = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?outcome=losing_tp&limit=500", headers=AUTH
    ).json()
    assert filtered["outcome"] == "losing_tp"
    assert filtered["total"] == len(expected)
    assert {t["id"] for t in filtered["trades"]} == {t["id"] for t in expected}
    for t in filtered["trades"]:
        assert t["exit_reason"] == "TAKE_PROFIT" and t["net_pnl"] < 0

    # An unrecognised outcome is rejected rather than silently ignored.
    bad = ctx.client.get(
        f"/api/backtest/strategies/{sid}/trades?outcome=bogus", headers=AUTH
    )
    assert bad.status_code == 422


def test_trades_endpoint_404_and_auth(ctx):
    assert ctx.client.get("/api/backtest/strategies/nope/trades").status_code == 401
    assert (
        ctx.client.get("/api/backtest/strategies/nope/trades", headers=AUTH).status_code
        == 404
    )


async def test_run_rejects_double_launch(ctx):
    sid = ctx.client.post("/api/backtest/strategies", json=_CREATE, headers=AUTH).json()["id"]
    # Force the row into RUNNING so a second run is rejected.
    await ctx.repo.update(sid, {"status": "RUNNING"})
    r = ctx.client.post(f"/api/backtest/strategies/{sid}/run", headers=AUTH)
    assert r.status_code == 409


# ── seed defaults ────────────────────────────────────────────────────────────


def test_seed_defaults_creates_s1_to_s4(ctx):
    r = ctx.client.post("/api/backtest/seed-defaults", headers=AUTH)
    assert r.status_code == 201
    assert r.json()["count"] == 4
    names = {s["name"] for s in ctx.client.get("/api/backtest/strategies", headers=AUTH).json()["strategies"]}
    assert len([n for n in names if n.startswith("S")]) == 4
    # Idempotent — a second seed creates nothing.
    r2 = ctx.client.post("/api/backtest/seed-defaults", headers=AUTH)
    assert r2.json()["count"] == 0
