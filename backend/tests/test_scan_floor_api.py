"""
Integration tests for the runtime scan-floor control (WS1, Slice 1a).

  GET  /api/system/health      — reports the active `scan_floor`.
  GET  /api/system/scan-floor  — the active liquidity floor.
  POST /api/system/scan-floor  — sets it app-wide (no restart).

The floor drives what the live/manual scan surfaces (both exchange clients read
`config.MIN_LIQUIDITY_USD` at scan time). It is a tractability knob, not alpha.
The fixture saves/restores the module-level global so a set can't leak between
tests, mirroring test_data_source_api.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
from app import create_app

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client():
    original = config.MIN_LIQUIDITY_USD
    config.set_min_liquidity_usd(1_000_000.0)
    yield TestClient(create_app())
    config.MIN_LIQUIDITY_USD = original


def _health(client) -> dict:
    return client.get("/api/system/health", headers=AUTH).json()


def test_set_scan_floor_requires_auth(client):
    r = client.post("/api/system/scan-floor", json={"min_liquidity_usd": 5_000_000})
    assert r.status_code == 401


def test_get_scan_floor_requires_auth(client):
    assert client.get("/api/system/scan-floor").status_code == 401


def test_rejects_negative_floor(client):
    r = client.post(
        "/api/system/scan-floor", json={"min_liquidity_usd": -1}, headers=AUTH
    )
    assert r.status_code == 422
    # Rejected → global unchanged.
    assert config.MIN_LIQUIDITY_USD == 1_000_000.0


def test_rejects_absurd_floor(client):
    r = client.post(
        "/api/system/scan-floor",
        json={"min_liquidity_usd": config.MIN_LIQUIDITY_USD_MAX + 1},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_set_changes_active_floor_and_health(client):
    assert _health(client)["scan_floor"] == 1_000_000.0
    assert client.get("/api/system/scan-floor", headers=AUTH).json() == {
        "min_liquidity_usd": 1_000_000.0
    }

    r = client.post(
        "/api/system/scan-floor", json={"min_liquidity_usd": 5_000_000}, headers=AUTH
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"min_liquidity_usd": 5_000_000.0, "previous": 1_000_000.0}

    # Global mutated → every call-time reader (both exchange clients) + health see it.
    assert config.MIN_LIQUIDITY_USD == 5_000_000.0
    assert _health(client)["scan_floor"] == 5_000_000.0
    assert (
        client.get("/api/system/scan-floor", headers=AUTH).json()["min_liquidity_usd"]
        == 5_000_000.0
    )


def test_zero_floor_is_allowed(client):
    # 0 = "no floor" — a valid choice (every cached market clears it).
    r = client.post(
        "/api/system/scan-floor", json={"min_liquidity_usd": 0}, headers=AUTH
    )
    assert r.status_code == 200
    assert config.MIN_LIQUIDITY_USD == 0.0
