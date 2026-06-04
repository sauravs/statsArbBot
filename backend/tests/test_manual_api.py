"""
Integration tests for the manual-trading HTTP surface (Phase 4, PRD F4).

Real FastAPI app + mocked dYdX client + in-memory repositories. Exercises the
record → list → close lifecycle and the error paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.scan_repository as scan_repo_module
import manual.repository as manual_repo_module
from app import create_app
from tests.conftest import (
    FakeDydxClient,
    FakeManualTradeRepository,
    FakeScanRepository,
    make_cointegrated_series,
    make_independent_walk,
)

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from scan.state import SCAN_STATE

    SCAN_STATE.__init__()

    monkeypatch.setattr(scan_repo_module, "_repo", FakeScanRepository())
    monkeypatch.setattr(manual_repo_module, "_repo", FakeManualTradeRepository())

    s1, s2 = make_cointegrated_series()
    noise = make_independent_walk()
    fake_client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "ZZZ-USD": noise})
    monkeypatch.setattr(
        "exchanges.dydx.client.DydxDataClient", lambda *a, **k: fake_client
    )
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "pairs.csv"))
    return TestClient(create_app())


def _scan(client):
    r = client.post("/api/scan/start", json={"quick": True}, headers=AUTH)
    assert r.status_code == 202
    assert client.get("/api/scan/status", headers=AUTH).json()["pairs_found"] >= 1


def _record(client, base="AAA-USD", quote="BBB-USD", c1=100.0, c2=100.0):
    return client.post(
        "/api/manual/record",
        json={
            "base_market": base,
            "quote_market": quote,
            "capital_leg1_usd": c1,
            "capital_leg2_usd": c2,
        },
        headers=AUTH,
    )


def test_manual_requires_auth(client):
    assert client.get("/api/manual").status_code == 401
    assert client.post("/api/manual/record", json={
        "base_market": "AAA-USD", "quote_market": "BBB-USD",
        "capital_leg1_usd": 100, "capital_leg2_usd": 100,
    }).status_code == 401
    assert client.post("/api/manual/x/close", json={
        "exit_price_leg1": 1, "exit_price_leg2": 1,
    }).status_code == 401


def test_record_then_list_then_close(client):
    _scan(client)

    # Record.
    r = _record(client, c1=100.0, c2=100.0)
    assert r.status_code == 201, r.text
    trade = r.json()
    assert trade["status"] == "OPEN"
    assert trade["base_market"] == "AAA-USD"
    assert trade["entry_price_leg1"] > 0 and trade["entry_price_leg2"] > 0
    assert trade["pnl"] is None and trade["closed_at"] is None
    tid = trade["id"]

    # List shows the open trade.
    lst = client.get("/api/manual", headers=AUTH).json()
    assert lst["count"] == 1
    assert lst["trades"][0]["id"] == tid

    # Close with exit prices → P&L computed, status CLOSED.
    e1 = trade["entry_price_leg1"] * 1.1
    e2 = trade["entry_price_leg2"] * 0.9
    closed = client.post(
        f"/api/manual/{tid}/close",
        json={"exit_price_leg1": e1, "exit_price_leg2": e2},
        headers=AUTH,
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "CLOSED"
    assert body["closed_at"] is not None
    assert body["pnl"] is not None
    assert "pnl_breakdown" in body
    assert body["pnl"] == pytest.approx(
        body["pnl_breakdown"]["pnl_leg1"] + body["pnl_breakdown"]["pnl_leg2"]
    )


def test_record_unknown_pair_404(client):
    _scan(client)
    r = _record(client, base="BBB-USD", quote="AAA-USD")  # reversed = not scanned
    assert r.status_code == 404


def test_record_before_scan_404(client):
    assert _record(client).status_code == 404


def test_record_rejects_nonpositive_capital(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 0,
            "capital_leg2_usd": 100,
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_double_close_returns_409(client):
    _scan(client)
    tid = _record(client).json()["id"]
    body = {"exit_price_leg1": 10.0, "exit_price_leg2": 10.0}
    assert client.post(f"/api/manual/{tid}/close", json=body, headers=AUTH).status_code == 200
    assert client.post(f"/api/manual/{tid}/close", json=body, headers=AUTH).status_code == 409


def test_record_rejects_unknown_exchange(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 100,
            "capital_leg2_usd": 100,
            "exchange": "kraken",
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_list_rejects_unknown_mode(client):
    r = client.get("/api/manual", params={"mode": "bogus"}, headers=AUTH)
    assert r.status_code == 422


def test_close_unknown_trade_404(client):
    r = client.post(
        "/api/manual/nope/close",
        json={"exit_price_leg1": 10.0, "exit_price_leg2": 10.0},
        headers=AUTH,
    )
    assert r.status_code == 404


# --- issue #37 PR-2: current prices + portfolio -----------------------------


def test_pair_prices_after_scan(client):
    _scan(client)
    r = client.get("/api/pairs/prices", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    # Both legs of the scanned AAA/BBB pair are priced with positive floats.
    assert body["prices"]["AAA-USD"] > 0
    assert body["prices"]["BBB-USD"] > 0


def test_pair_prices_before_scan_empty(client):
    r = client.get("/api/pairs/prices", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"prices": {}, "error": None}


def test_portfolio_open_trade_marked_to_market(client):
    _scan(client)
    _record(client, c1=120.0, c2=80.0)

    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p["error"] is None
    assert p["open_count"] == 1 and p["closed_count"] == 0
    assert p["allocated_capital"] == pytest.approx(200.0)  # 120 + 80
    assert p["realized_pnl"] == pytest.approx(0.0)
    # Marked to market at the current close, which equals the entry close for the
    # static fake series → ~0 unrealized P&L (but priced, so not None).
    assert p["unrealized_pnl"] == pytest.approx(0.0, abs=1e-6)


def test_portfolio_realized_after_close(client):
    _scan(client)
    trade = _record(client, c1=100.0, c2=100.0).json()
    closed = client.post(
        f"/api/manual/{trade['id']}/close",
        json={
            "exit_price_leg1": trade["entry_price_leg1"] * 1.1,
            "exit_price_leg2": trade["entry_price_leg2"] * 0.9,
        },
        headers=AUTH,
    ).json()

    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p["open_count"] == 0 and p["closed_count"] == 1
    assert p["allocated_capital"] == pytest.approx(0.0)  # no OPEN trades
    assert p["unrealized_pnl"] is None  # nothing to mark to market
    assert p["realized_pnl"] == pytest.approx(closed["pnl"])


def test_portfolio_empty(client):
    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p == {
        "allocated_capital": 0.0,
        "unrealized_pnl": None,
        "realized_pnl": 0.0,
        "open_count": 0,
        "closed_count": 0,
        "error": None,
    }


def test_portfolio_rejects_unknown_mode(client):
    r = client.get("/api/manual/portfolio", params={"mode": "bogus"}, headers=AUTH)
    assert r.status_code == 422
