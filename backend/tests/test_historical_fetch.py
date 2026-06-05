"""
Tests for the live historical-data fetch by date range (issue #81).

Validation + range cap, the fetch→clean→merge-within-range job (with an injected
fake indexer client + in-memory cache repo), cancel-between-markets, and the router
error mappings. No network — the client is faked via ``make_fetch_client``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
import ingest.cache_repository as cache_repo_module
import ingest.historical_fetch as hf
from app import create_app
from tests.conftest import FakeOhlcvCacheRepository

AUTH = {"X-API-Key": config.API_KEY}
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 1, 4, tzinfo=timezone.utc)


def _candle(ts: datetime, base: float) -> dict:
    """A clean, OHLC-consistent, non-flat candle with volume."""
    return {
        "startedAt": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "open": base,
        "high": base + 2,
        "low": base - 1,
        "close": base + 1,
        "baseTokenVolume": 1000.0,
    }


class FakeFetchClient:
    """Canned indexer responses. ``on_fetch`` lets a test trigger a side effect
    (e.g. request cancel) when a market's candles are fetched."""

    def __init__(self, markets, on_fetch=None):
        self._markets = markets
        self._on_fetch = on_fetch

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_markets(self):
        return {m: {"volume24H": "999999"} for m in self._markets}

    async def fetch_ohlcv_range(self, market, start, end):
        if self._on_fetch:
            self._on_fetch(market)
        # 4 hourly candles inside the window.
        return [_candle(START + timedelta(hours=h), 100.0 + h) for h in range(4)]

    async def fetch_funding_range(self, market, start, end):
        return [
            {"effectiveAt": (START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
             "rate": "0.0001"}
            for h in range(4)
        ]


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(hf, "_state", hf.FetchState())
    monkeypatch.setattr(cache_repo_module, "_repo", FakeOhlcvCacheRepository())
    yield


# ── validation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_inverted_range():
    with pytest.raises(ValueError):
        await hf.start_fetch(END, START)


@pytest.mark.asyncio
async def test_rejects_future_end():
    future = datetime.now(timezone.utc) + timedelta(days=2)
    with pytest.raises(ValueError):
        await hf.start_fetch(future, future + timedelta(hours=1))


@pytest.mark.asyncio
async def test_rejects_oversized_range():
    big_end = START + timedelta(days=config.DATA_FETCH_MAX_DAYS + 5)
    with pytest.raises(ValueError):
        await hf.start_fetch(START, big_end)


# ── the job ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_fetches_cleans_and_merges(monkeypatch):
    monkeypatch.setattr(hf, "_state", hf.FetchState(running=True))
    monkeypatch.setattr(
        hf, "make_fetch_client", lambda: FakeFetchClient(["ADA-USD", "BTC-USD"])
    )
    await hf._run(START, END)

    st = hf.get_state()
    assert st["running"] is False
    assert st["total_markets"] == 2 and st["markets_done"] == 2
    assert {r["market"]: r["status"] for r in st["results"]} == {
        "ADA-USD": "ok",
        "BTC-USD": "ok",
    }
    assert all(r["bars"] == 4 for r in st["results"])

    # Rows actually merged into the cache repo (within the window).
    repo = cache_repo_module._repo
    assert len(repo.candles[(config.DEFAULT_EXCHANGE, "ADA-USD", config.CANDLE_RESOLUTION)]) == 4
    assert len(repo.funding[(config.DEFAULT_EXCHANGE, "ADA-USD")]) == 4


@pytest.mark.asyncio
async def test_merge_preserves_out_of_window_bars(monkeypatch):
    repo = FakeOhlcvCacheRepository()
    # Pre-existing bar OUTSIDE the fetch window must survive the merge.
    older = START - timedelta(days=10)
    key = (config.DEFAULT_EXCHANGE, "ADA-USD", config.CANDLE_RESOLUTION)
    repo.candles[key] = [{"timestamp": older, "close": 1.0}]
    monkeypatch.setattr(cache_repo_module, "_repo", repo)
    monkeypatch.setattr(hf, "_state", hf.FetchState(running=True))
    monkeypatch.setattr(hf, "make_fetch_client", lambda: FakeFetchClient(["ADA-USD"]))

    await hf._run(START, END)

    timestamps = [r["timestamp"] for r in repo.candles[key]]
    assert older in timestamps  # untouched
    assert len(timestamps) == 5  # 1 old + 4 new


@pytest.mark.asyncio
async def test_cancel_stops_at_next_market(monkeypatch):
    monkeypatch.setattr(hf, "_state", hf.FetchState(running=True))
    # Trigger cancel while fetching the first market → loop breaks before the 2nd.
    monkeypatch.setattr(
        hf,
        "make_fetch_client",
        lambda: FakeFetchClient(["A-USD", "B-USD", "C-USD"], on_fetch=lambda m: hf.request_cancel()),
    )
    await hf._run(START, END)

    st = hf.get_state()
    assert st["cancelled"] is True
    assert st["markets_done"] == 1  # only the first market completed


# ── router ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(create_app())


def test_fetch_requires_auth(client):
    assert client.post("/api/data/fetch", json={"start": START.isoformat(), "end": END.isoformat()}).status_code == 401


def test_fetch_rejects_bad_range(client):
    r = client.post(
        "/api/data/fetch",
        json={"start": END.isoformat(), "end": START.isoformat()},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_fetch_conflict_when_running(client, monkeypatch):
    monkeypatch.setattr(hf, "_state", hf.FetchState(running=True))
    r = client.post(
        "/api/data/fetch",
        json={"start": START.isoformat(), "end": END.isoformat()},
        headers=AUTH,
    )
    assert r.status_code == 409


def test_status_and_cancel_shape(client):
    assert client.get("/api/data/fetch/status", headers=AUTH).json()["running"] is False
    assert "cancel_requested" in client.post("/api/data/fetch/cancel", headers=AUTH).json()
