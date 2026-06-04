"""
Integration tests for the runtime market-data-source toggle (issue #43).

  GET  /api/system/health        — reports the active `data_source`.
  POST /api/system/data-source   — switches it app-wide (no restart), clearing
                                   the latest scan's pairs for the default scope.

Uses a real app + an in-memory scan repository. The fixture saves/restores the
module-level ``config.SCAN_DATA_SOURCE`` so a switch can't leak between tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.scan_repository as scan_repo_module
from app import create_app
from tests.conftest import FakeScanRepository

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(scan_repo_module, "_repo", FakeScanRepository())
    # Save/restore the global so the runtime switch doesn't bleed across tests.
    original = config.SCAN_DATA_SOURCE
    config.set_scan_data_source("fake")
    yield TestClient(create_app())
    config.SCAN_DATA_SOURCE = original


def _health(client) -> dict:
    return client.get("/api/system/health", headers=AUTH).json()


def test_set_data_source_requires_auth(client):
    assert client.post("/api/system/data-source", json={"source": "dydx"}).status_code == 401


def test_rejects_invalid_source(client):
    r = client.post("/api/system/data-source", json={"source": "bogus"}, headers=AUTH)
    assert r.status_code == 422


def test_switch_changes_active_source_and_health(client):
    assert _health(client)["data_source"] == "fake"

    r = client.post("/api/system/data-source", json={"source": "dydx"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"data_source": "dydx", "previous": "fake", "pairs_cleared": True}

    # Global mutated → every call-time reader (and health) sees the new source.
    assert config.SCAN_DATA_SOURCE == "dydx"
    assert _health(client)["data_source"] == "dydx"


def test_switch_clears_stale_pairs(client):
    # Seed pairs as if a scan had run under the previous source (direct store
    # write — keys cover what get_latest_pairs sorts on + what /api/pairs reads).
    scan_repo_module._repo.store[(config.DEFAULT_EXCHANGE, config.DEFAULT_MODE)] = [
        {
            "base_market": "DEMO1-USD",
            "quote_market": "DEMO2-USD",
            "zero_crossings": 5,
            "p_value": 0.01,
            "scanned_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    assert client.get("/api/pairs", headers=AUTH).json()["count"] == 1

    client.post("/api/system/data-source", json={"source": "dydx"}, headers=AUTH)

    after = client.get("/api/pairs", headers=AUTH).json()
    assert after["count"] == 0  # stale demo pairs cleared on switch


def test_same_source_is_noop_no_clear(client):
    r = client.post("/api/system/data-source", json={"source": "fake"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"data_source": "fake", "previous": "fake", "pairs_cleared": False}


def test_source_is_normalized(client):
    r = client.post("/api/system/data-source", json={"source": "  DYDX  "}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["data_source"] == "dydx"
