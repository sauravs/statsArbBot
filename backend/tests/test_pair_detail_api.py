"""
Integration tests for the pair-detail series endpoint (Phase 3, PRD F3).

Exercises the real FastAPI app with a mocked dYdX client and an in-memory
repository: scan first so the pair exists, then GET its chart series.
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
    from scan.state import SCAN_STATE

    SCAN_STATE.__init__()

    fake_repo = FakeScanRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", fake_repo)

    s1, s2 = make_cointegrated_series()
    noise = make_independent_walk()
    fake_client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "ZZZ-USD": noise})
    # The series endpoint builds its own client via exchanges.make_data_client →
    # exchanges.dydx.client.DydxDataClient; patch that to the shared fake.
    monkeypatch.setattr(
        "exchanges.dydx.client.DydxDataClient", lambda *a, **k: fake_client
    )
    monkeypatch.setattr(
        config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "pairs.csv")
    )
    return TestClient(create_app())


def _run_scan(client):
    r = client.post("/api/scan/start", json={"quick": True}, headers=AUTH)
    assert r.status_code == 202
    status = client.get("/api/scan/status", headers=AUTH).json()
    assert status["running"] is False and status["pairs_found"] >= 1


def test_series_requires_auth(client):
    assert client.get("/api/pairs/AAA-USD/BBB-USD/series").status_code == 401


def test_series_for_scanned_pair(client):
    _run_scan(client)
    resp = client.get("/api/pairs/AAA-USD/BBB-USD/series", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()

    assert body["base_market"] == "AAA-USD"
    assert body["quote_market"] == "BBB-USD"
    assert body["count"] >= 1
    # Thresholds carried for the chart's reference lines (Option-B defaults).
    assert body["entry_threshold"] == config.ZSCORE_THRESH
    assert body["exit_threshold"] == config.EXIT_ZSCORE
    assert body["stop_threshold"] == config.STOP_LOSS_ZSCORE

    # Three panels present and populated.
    norm = body["normalized"]
    assert len(norm["base"]) == len(norm["quote"]) >= 1
    assert norm["base"][0]["value"] == pytest.approx(100.0)
    assert norm["quote"][0]["value"] == pytest.approx(100.0)

    spread = body["spread"]
    assert "mean" in spread and "std" in spread
    assert len(spread["series"]) >= 1

    z = body["zscore"]
    assert len(z["series"]) >= 1
    # Markers (if any) are well-formed.
    for m in z["markers"]:
        assert m["kind"] in ("entry", "exit")
        assert set(m) == {"time", "kind", "side", "reason", "zscore"}


def test_series_unknown_pair_404(client):
    _run_scan(client)
    # Reversed orientation was not the scanned pair.
    resp = client.get("/api/pairs/BBB-USD/AAA-USD/series", headers=AUTH)
    assert resp.status_code == 404


def test_series_before_scan_404(client):
    resp = client.get("/api/pairs/AAA-USD/BBB-USD/series", headers=AUTH)
    assert resp.status_code == 404
