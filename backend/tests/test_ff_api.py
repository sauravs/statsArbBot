"""
Integration tests for the fast-forward HTTP surface (Phase 7, PRD F7.3).

Real FastAPI app + in-memory ``FakeFFRepository`` / ``FakeScanRepository`` + an
injected demo candle source. Under Starlette's TestClient a ``BackgroundTasks``
job runs to completion before the POST response is delivered, so the create →
GET-detail flow deterministically observes a COMPLETED run with its aggregates.
Also covers list, 404, the no-pairs 409, validation, and auth.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
import db.ff_repository as ff_repo_module
import db.scan_repository as scan_repo_module
import replay.engine as engine_module
from app import create_app
from tests.conftest import FakeFFRepository, FakeScanRepository

AUTH = {"X-API-Key": config.API_KEY}
_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
_N = 220


class FakeCandleSource:
    def __init__(self, candles):
        self._candles = candles

    async def get_candles(self, market, *, start, end):
        return [c for c in self._candles.get(market, []) if start <= c["timestamp"] <= end]

    async def get_funding(self, market, *, start, end):
        return []


def _series():
    rng = np.random.default_rng(7)
    s2 = 100 + np.cumsum(rng.normal(0, 1, _N))
    eps = np.zeros(_N)
    for t in range(1, _N):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.6)
    s1 = 2.0 * s2 + 5.0 + eps
    candles = {
        m: [{"timestamp": _ANCHOR + timedelta(hours=i), "close": float(c)} for i, c in enumerate(s)]
        for m, s in (("AAA-USD", s1), ("BBB-USD", s2))
    }
    return candles


@pytest.fixture
def ctx(monkeypatch):
    scan_repo = FakeScanRepository()
    ff_repo = FakeFFRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", scan_repo)
    monkeypatch.setattr(ff_repo_module, "_repo", ff_repo)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    monkeypatch.setattr(
        engine_module, "make_candle_source", lambda **_: FakeCandleSource(_series())
    )
    client = TestClient(create_app())
    return types.SimpleNamespace(client=client, scan_repo=scan_repo, ff_repo=ff_repo)


async def _seed_pairs(ctx):
    await ctx.scan_repo.replace_scan_results(
        [{
            "base_market": "AAA-USD", "quote_market": "BBB-USD",
            "hedge_ratio": 2.0, "intercept": 5.0, "half_life": 2.0,
            "zero_crossings": 40, "p_value": 0.001, "z_score": 0.0, "spread_std": 1.0,
            "scanned_at": _ANCHOR, "window_start": _ANCHOR, "window_end": _ANCHOR,
            "exchange": "dydx", "mode": config.DEFAULT_MODE,
        }],
        exchange="dydx", mode=config.DEFAULT_MODE,
    )


_BODY = {
    "label": "api run",
    "start_time": (_ANCHOR + timedelta(hours=21)).isoformat(),
    "end_time": (_ANCHOR + timedelta(hours=_N - 1)).isoformat(),
    "entry_threshold": 0.5, "exit_threshold": 0.5,
    "slippage_pct": 0.0, "taker_fee_pct": 0.0, "zscore_window": 21,
}


# ── auth / validation ────────────────────────────────────────────────────────


def test_endpoints_require_auth(ctx):
    assert ctx.client.get("/api/ff/simulations").status_code == 401
    assert ctx.client.post("/api/ff/simulations", json={}).status_code == 401


@pytest.mark.parametrize("body", [
    {"entry_threshold": 0.1},                 # below 0.5
    {"stop_threshold": 0.0},                  # below 1.0
    {"starting_capital": 0},                  # not > 0
    {"start_time": (_ANCHOR + timedelta(hours=300)).isoformat(),
     "end_time": (_ANCHOR + timedelta(hours=10)).isoformat()},  # start >= end
])
async def test_validation_rejects_bad_params(ctx, body):
    await _seed_pairs(ctx)
    payload = {**_BODY, **body}
    r = ctx.client.post("/api/ff/simulations", json=payload, headers=AUTH)
    assert r.status_code == 422, r.text


async def test_create_without_pairs_409(ctx):
    # No scan seeded → nothing to replay.
    r = ctx.client.post("/api/ff/simulations", json=_BODY, headers=AUTH)
    assert r.status_code == 409


# ── lifecycle ────────────────────────────────────────────────────────────────


async def test_create_runs_and_completes(ctx):
    await _seed_pairs(ctx)
    r = ctx.client.post("/api/ff/simulations", json=_BODY, headers=AUTH)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["status"] == "RUNNING"  # snapshot at creation
    ff_id = created["id"]

    # The background replay completed before the POST returned (TestClient).
    detail = ctx.client.get(f"/api/ff/simulations/{ff_id}", headers=AUTH).json()
    assert detail["status"] == "COMPLETED"
    assert detail["total_trades"] > 0
    assert detail["progress"] == 1.0
    assert detail["equity_curve"]
    assert "AAA-USD/BBB-USD" in detail["per_pair_pnl"]
    assert sum(detail["exit_reasons"].values()) == detail["total_trades"]


async def test_list_returns_runs(ctx):
    await _seed_pairs(ctx)
    ctx.client.post("/api/ff/simulations", json=_BODY, headers=AUTH)
    r = ctx.client.get("/api/ff/simulations", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["simulations"][0]["label"] == "api run"


def test_detail_404(ctx):
    assert ctx.client.get("/api/ff/simulations/nope", headers=AUTH).status_code == 404


def test_stop_404(ctx):
    assert ctx.client.post("/api/ff/simulations/nope/stop", headers=AUTH).status_code == 404


async def test_default_window_offline(ctx):
    # In fake mode start/end may be omitted — defaults to the demo history window.
    await _seed_pairs(ctx)
    body = {k: v for k, v in _BODY.items() if k not in ("start_time", "end_time")}
    r = ctx.client.post("/api/ff/simulations", json=body, headers=AUTH)
    assert r.status_code == 201, r.text
    assert r.json()["start_time"] is not None
