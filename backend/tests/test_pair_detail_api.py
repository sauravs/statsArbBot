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

    fake_repo = FakeScanRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", fake_repo)
    # The series endpoint falls back to a recorded manual trade when the pair is
    # not in the latest scan (issue #137); patch its repo to an in-memory fake.
    monkeypatch.setattr(manual_repo_module, "_repo", FakeManualTradeRepository())

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

    # Raw (actual) per-leg prices for the dual-axis panel (issue #68): same length
    # as the normalized overlay, positive prices, distinct from the rebased values.
    raw = body["raw"]
    assert len(raw["base"]) == len(norm["base"]) >= 1
    assert len(raw["quote"]) == len(norm["quote"]) >= 1
    assert all(p["value"] > 0 for p in raw["base"])
    assert all(p["value"] > 0 for p in raw["quote"])
    # The normalized series is rebased to 100 at the window start; raw is not.
    assert raw["base"][0]["value"] != pytest.approx(100.0)

    z = body["zscore"]
    assert len(z["series"]) >= 1
    # Markers (if any) are well-formed.
    for m in z["markers"]:
        assert m["kind"] in ("entry", "exit")
        assert set(m) == {"time", "kind", "side", "reason", "zscore"}


def test_series_uses_concurrent_two_page_fast_path(client, monkeypatch):
    """Issue #61: the chart fetches a small, concurrently-fetched page count so a
    live pair-detail chart loads in seconds rather than the full-history minutes."""
    import routers.pairs as pairs_router
    from marketdata.pair_series import build_pair_series as real_builder

    captured: dict = {}

    async def spy(*args, **kwargs):
        captured["num_pages"] = kwargs.get("num_pages")
        captured["concurrent"] = kwargs.get("concurrent")
        return await real_builder(*args, **kwargs)

    monkeypatch.setattr(pairs_router, "build_pair_series", spy)

    _run_scan(client)
    resp = client.get("/api/pairs/AAA-USD/BBB-USD/series", headers=AUTH)
    assert resp.status_code == 200
    assert captured["num_pages"] == config.PAIR_CHART_PAGES == 2
    assert captured["concurrent"] is True


def test_series_unknown_pair_404(client):
    _run_scan(client)
    # Reversed orientation was not the scanned pair.
    resp = client.get("/api/pairs/BBB-USD/AAA-USD/series", headers=AUTH)
    assert resp.status_code == 404


def test_series_before_scan_404(client):
    resp = client.get("/api/pairs/AAA-USD/BBB-USD/series", headers=AUTH)
    assert resp.status_code == 404


async def _record_trade(base, quote):
    """Seed a manual trade in the fake repo for the (issue #137) fallback path."""
    from datetime import datetime, timezone

    await manual_repo_module.get_manual_trade_repository().create(
        {
            "exchange": config.DEFAULT_EXCHANGE,
            "mode": config.DEFAULT_MODE,
            "data_source": config.SCAN_DATA_SOURCE,
            "base_market": base,
            "quote_market": quote,
            "hedge_ratio": 1.5,
            "half_life": 12.0,
            "z_score": -1.2,
            "spread_value": 3.4,
            "entry_price_leg1": 100.0,
            "entry_price_leg2": 50.0,
            "capital_leg1_usd": 100.0,
            "capital_leg2_usd": 100.0,
            "recorded_at": datetime.now(timezone.utc),
        }
    )


def test_series_falls_back_to_recorded_trade(client):
    """A pair that left the latest scan but has a recorded trade still charts."""
    import asyncio

    # No scan was run, so the scan lookup misses — but a trade exists for the pair.
    asyncio.run(_record_trade("AAA-USD", "BBB-USD"))
    resp = client.get("/api/pairs/AAA-USD/BBB-USD/series", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_market"] == "AAA-USD"
    # The fallback reuses the trade's stored β and defaults intercept (α) to 0.
    assert body["hedge_ratio"] == 1.5
    assert body["intercept"] == 0.0
    assert body["count"] >= 1


def test_series_no_scan_no_trade_still_404(client):
    """Never scanned *and* never traded → still a 404 (fallback finds nothing)."""
    resp = client.get("/api/pairs/ZZZ-USD/AAA-USD/series", headers=AUTH)
    assert resp.status_code == 404
