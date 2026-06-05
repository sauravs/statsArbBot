"""
Tests for the historical-data inventory endpoint (issue #80).

  GET /api/data/inventory — per-market OHLCV coverage (bars, range, completeness)
                            + a funding summary. Read-only.

Uses a real app + the in-memory FakeOhlcvCacheRepository, so no DB is needed; the
completeness maths (bars vs a gapless series) and the summary aggregation are
exercised over seeded bars with a deliberate gap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
import ingest.cache_repository as cache_repo_module
from app import create_app
from tests.conftest import FakeOhlcvCacheRepository

AUTH = {"X-API-Key": config.API_KEY}
EX = config.DEFAULT_EXCHANGE
RES = config.CANDLE_RESOLUTION  # "1HOUR" → 3600s step


def _bars(start: datetime, hours: list[int]) -> list[dict]:
    return [
        {"timestamp": start + timedelta(hours=h), "close": 100.0 + h} for h in hours
    ]


@pytest.fixture
def client(monkeypatch):
    repo = FakeOhlcvCacheRepository()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # ADA: 3 consecutive hourly bars → gapless (completeness 1.0).
    repo.candles[(EX, "ADA-USD", RES)] = _bars(start, [0, 1, 2])
    # BTC: 2 bars spanning 3 hours (missing 01:00) → completeness 2/3.
    repo.candles[(EX, "BTC-USD", RES)] = _bars(start, [0, 2])
    repo.funding[(EX, "ADA-USD")] = [{"timestamp": start, "funding_rate": 0.0001}] * 2
    monkeypatch.setattr(cache_repo_module, "_repo", repo)
    return TestClient(create_app())


def test_inventory_requires_auth(client):
    assert client.get("/api/data/inventory").status_code == 401


def test_inventory_reports_coverage_and_summary(client):
    r = client.get("/api/data/inventory", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["exchange"] == EX
    assert body["resolution"] == RES

    markets = body["markets"]
    assert [m["market"] for m in markets] == ["ADA-USD", "BTC-USD"]  # sorted

    ada, btc = markets
    assert ada["bars"] == 3 and ada["completeness"] == 1.0
    assert btc["bars"] == 2 and btc["completeness"] == round(2 / 3, 4)
    assert ada["first"].startswith("2024-01-01T00:00")
    assert ada["last"].startswith("2024-01-01T02:00")

    summary = body["summary"]
    assert summary["market_count"] == 2
    assert summary["total_bars"] == 5
    assert summary["earliest"].startswith("2024-01-01T00:00")
    assert summary["latest"].startswith("2024-01-01T02:00")
    assert summary["funding_markets"] == 1
    assert summary["funding_rows"] == 2


def test_inventory_empty_cache(monkeypatch):
    monkeypatch.setattr(cache_repo_module, "_repo", FakeOhlcvCacheRepository())
    body = TestClient(create_app()).get("/api/data/inventory", headers=AUTH).json()
    assert body["markets"] == []
    assert body["summary"]["market_count"] == 0
    assert body["summary"]["earliest"] is None
    assert body["summary"]["total_bars"] == 0
