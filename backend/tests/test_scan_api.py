"""
Integration tests for the scan/pairs HTTP surface.

Exercises the real FastAPI app and routers with a mocked dYdX client and an
in-memory repository (no network, no Prisma). Verifies the end-to-end slice:
POST /api/scan/start → background scan runs → dual-write → GET /api/pairs reads
the persisted result back (the "survive reload" gate).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.scan_repository as scan_repo_module
from app import create_app
from tests.conftest import (
    FakeDydxClient,
    FakeScanRepository,
    make_cointegrated_series,
    make_independent_walk,
)

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Fresh global scan state per test.
    from scan.state import SCAN_STATE

    SCAN_STATE.__init__()  # reset dataclass fields + lock

    # In-memory repo shared by the orchestrator and the /api/pairs router.
    fake_repo = FakeScanRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", fake_repo)

    # The orchestrator's owned dYdX client → a fake serving synthetic series.
    s1, s2 = make_cointegrated_series()
    noise = make_independent_walk()
    fake_client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "ZZZ-USD": noise})
    monkeypatch.setattr(
        "exchanges.dydx.client.DydxDataClient", lambda *a, **k: fake_client
    )

    monkeypatch.setattr(
        config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "pairs.csv")
    )
    return TestClient(create_app())


def test_pairs_requires_auth(client):
    assert client.get("/api/pairs").status_code == 401
    assert client.post("/api/scan/start", json={"quick": True}).status_code == 401


def test_scan_then_pairs_roundtrip(client):
    # No scan yet → empty.
    r0 = client.get("/api/pairs", headers=AUTH)
    assert r0.status_code == 200
    assert r0.json()["count"] == 0

    # Start a scan; TestClient runs the background task before returning.
    start = client.post("/api/scan/start", json={"quick": True}, headers=AUTH)
    assert start.status_code == 202
    assert start.json()["started"] is True

    # Scan settled.
    status = client.get("/api/scan/status", headers=AUTH).json()
    assert status["running"] is False
    assert status["pairs_found"] >= 1
    assert status["error"] is None

    # Pairs persisted and readable (survives "reload" — fresh GET from the repo).
    pairs = client.get("/api/pairs", headers=AUTH).json()
    assert pairs["count"] >= 1
    assert pairs["scanned_at"] is not None
    found = {(p["base_market"], p["quote_market"]) for p in pairs["pairs"]}
    assert ("AAA-USD", "BBB-USD") in found
    row = pairs["pairs"][0]
    assert "z_score" in row and "half_life" in row and "intercept" in row


def test_double_start_returns_409(client):
    # Simulate an in-flight scan so the start guard rejects a concurrent request.
    from scan.state import SCAN_STATE

    SCAN_STATE.running = True
    try:
        resp = client.post("/api/scan/start", json={"quick": True}, headers=AUTH)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Scan already running"
    finally:
        SCAN_STATE.running = False


def test_stop_requires_auth(client):
    assert client.post("/api/scan/stop").status_code == 401


def test_stop_when_idle_returns_409(client):
    resp = client.post("/api/scan/stop", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "No scan is running"


def test_stop_flags_running_scan(client):
    # Simulate an in-flight scan; stop flags it and reports back (issue #59).
    from scan.state import SCAN_STATE

    SCAN_STATE.running = True
    try:
        resp = client.post("/api/scan/stop", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["stop_requested"] is True
        assert SCAN_STATE.stop_requested is True
    finally:
        SCAN_STATE.stop_requested = False
        SCAN_STATE.running = False


def test_exchange_list(client):
    resp = client.get("/exchange/list", headers=AUTH)
    assert resp.status_code == 200
    exchanges = {e["id"]: e for e in resp.json()["exchanges"]}
    assert exchanges["dydx"]["integrated"] is True
    assert exchanges["binance"]["integrated"] is False
