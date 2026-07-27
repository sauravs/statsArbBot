"""
Integration tests for the WS2 scan/manual-list minimisation (Phase-3 WS2).

  GET/POST /api/system/scan-list-filters — the runtime half-spread ceiling + top-N.
  GET      /api/pairs                     — enriches with a tradability score and
                                            applies the ceiling + top-N read-time.

Non-destructive: the stored scan is never touched; the knobs are process-global and
reset on restart. The fixture saves/restores the globals + clears the enrichment
memo so nothing leaks between tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.scan_repository as scan_repo_module
import scan.list_view as list_view
from app import create_app
from tests.conftest import FakeScanRepository

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client(monkeypatch):
    repo = FakeScanRepository()
    monkeypatch.setattr(scan_repo_module, "_repo", repo)
    list_view._enrich_cache.clear()
    # Save/restore the process globals so a set can't bleed across tests.
    orig = (config.SCAN_MAX_HALF_SPREAD_PCT, config.SCAN_TOP_N)
    config.set_scan_max_half_spread_pct(0.0)
    config.set_scan_top_n(0)
    yield TestClient(create_app()), repo
    config.SCAN_MAX_HALF_SPREAD_PCT, config.SCAN_TOP_N = orig


# ── The runtime endpoint ─────────────────────────────────────────────────────

def test_endpoint_requires_auth(client):
    c, _ = client
    assert c.get("/api/system/scan-list-filters").status_code == 401
    assert c.post("/api/system/scan-list-filters", json={"top_n": 5}).status_code == 401


def test_rejects_bad_values(client):
    c, _ = client
    assert c.post(
        "/api/system/scan-list-filters", json={"max_half_spread_pct": -1}, headers=AUTH
    ).status_code == 422
    assert c.post(
        "/api/system/scan-list-filters", json={"top_n": -3}, headers=AUTH
    ).status_code == 422
    # Both globals untouched by a rejected set.
    assert config.SCAN_MAX_HALF_SPREAD_PCT == 0.0
    assert config.SCAN_TOP_N == 0


def test_partial_update_and_health(client):
    c, _ = client
    assert c.get("/api/system/health", headers=AUTH).json()["scan_list_filters"] == {
        "max_half_spread_pct": 0.0,
        "top_n": 0,
    }
    # Set only top_n → ceiling stays put.
    r = c.post("/api/system/scan-list-filters", json={"top_n": 25}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"max_half_spread_pct": 0.0, "top_n": 25}
    # Set only the ceiling → top_n stays.
    r = c.post(
        "/api/system/scan-list-filters", json={"max_half_spread_pct": 0.05}, headers=AUTH
    )
    assert r.json() == {"max_half_spread_pct": 0.05, "top_n": 25}
    assert c.get("/api/system/health", headers=AUTH).json()["scan_list_filters"] == {
        "max_half_spread_pct": 0.05,
        "top_n": 25,
    }


# ── /api/pairs enrichment + minimisation ─────────────────────────────────────

def _seed(repo, exchange, mode):
    # Three cointegrated pairs; distinct half-life/p-value so the tradability score
    # (with the injected volumes below) strictly orders them AAA/BBB > CCC/DDD > EEE/FFF.
    repo.store[(exchange, mode)] = [
        {"base_market": "AAA-USD", "quote_market": "BBB-USD",
         "half_life": 6.0, "p_value": 0.01, "zero_crossings": 9,
         "scanned_at": "2026-01-01T00:00:00+00:00"},
        {"base_market": "CCC-USD", "quote_market": "DDD-USD",
         "half_life": 24.0, "p_value": 0.03, "zero_crossings": 5,
         "scanned_at": "2026-01-01T00:00:00+00:00"},
        {"base_market": "EEE-USD", "quote_market": "FFF-USD",
         "half_life": 60.0, "p_value": 0.049, "zero_crossings": 2,
         "scanned_at": "2026-01-01T00:00:00+00:00"},
    ]


@pytest.fixture
def seeded(client, monkeypatch):
    c, repo = client
    exchange, mode = config.active_exchange(), config.DEFAULT_MODE
    _seed(repo, exchange, mode)

    # Deterministic per-market dollar-volume (bypasses the DB / fake-mode short-circuit).
    vols = {
        "AAA-USD": 5_000_000.0, "BBB-USD": 4_000_000.0,   # thickest → min 4M
        "CCC-USD": 1_000_000.0, "DDD-USD": 900_000.0,     # min 900k
        "EEE-USD": 50_000.0, "FFF-USD": 40_000.0,         # thin → min 40k
    }

    async def _fake_dvols(exchange, markets):
        return {m: vols[m] for m in markets if m in vols}

    monkeypatch.setattr(list_view, "_dollar_volumes", _fake_dvols)
    # Deterministic half-spreads: EEE/FFF are wide; the rest tight.
    from simulation import spread_cost

    monkeypatch.setattr(
        spread_cost, "SEED_HALF_SPREAD_PCT",
        {"AAA-USD": 0.01, "BBB-USD": 0.01, "CCC-USD": 0.02, "DDD-USD": 0.02,
         "EEE-USD": 0.20, "FFF-USD": 0.20},
    )
    return c


def test_pairs_enriched_and_unfiltered_by_default(seeded):
    body = seeded.get("/api/pairs", headers=AUTH).json()
    assert body["count"] == 3 and body["total"] == 3
    assert body["filters"] == {"max_half_spread_pct": 0.0, "top_n": 0}
    first = body["pairs"][0]
    # Enrichment fields are present.
    for k in ("tradability", "min_dollar_volume", "max_half_spread_pct",
              "dollar_volume_base", "dollar_volume_quote"):
        assert k in first


def test_top_n_keeps_most_tradable(seeded):
    seeded.post("/api/system/scan-list-filters", json={"top_n": 1}, headers=AUTH)
    body = seeded.get("/api/pairs", headers=AUTH).json()
    assert body["count"] == 1 and body["total"] == 3
    # AAA/BBB is the thickest + fastest + strongest → highest tradability.
    assert body["pairs"][0]["base_market"] == "AAA-USD"


def test_half_spread_ceiling_drops_wide_pairs(seeded):
    seeded.post(
        "/api/system/scan-list-filters", json={"max_half_spread_pct": 0.05}, headers=AUTH
    )
    body = seeded.get("/api/pairs", headers=AUTH).json()
    # EEE/FFF (0.20% legs) dropped; the two tight pairs remain.
    kept = {p["base_market"] for p in body["pairs"]}
    assert kept == {"AAA-USD", "CCC-USD"}
    assert body["total"] == 3 and body["count"] == 2
