"""
Phase 0 backend smoke tests.

Exercise the app factory and the auth boundary without needing a database or the
generated Prisma client (DATABASE_URL is unset under test, so /api/system/health
reports the DB as disconnected rather than connecting).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import config
from app import create_app

client = TestClient(create_app())


def test_public_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_system_health_requires_api_key():
    resp = client.get("/api/system/health")
    assert resp.status_code == 401


def test_system_health_rejects_wrong_key():
    resp = client.get("/api/system/health", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_system_health_accepts_valid_key():
    resp = client.get("/api/system/health", headers={"X-API-Key": config.API_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "database" in body
