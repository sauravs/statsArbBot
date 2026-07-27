"""
Integration tests for the WS3 campaign endpoints (Phase-3 WS3, Slice 1).

  POST   /api/backtest/campaigns        — expand a grid spec → create member strategies.
  GET    /api/backtest/campaigns        — list campaigns.
  GET    /api/backtest/campaigns/{id}   — campaign + its members.
  DELETE /api/backtest/campaigns/{id}   — delete campaign; members detached, not deleted.

Real FastAPI app + in-memory campaign/strategy repositories (no DB). Slice 1 creates
members PENDING; execution is Slice 2.
"""

from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

import config
import db.backtest_repository as repo_module
import db.campaign_repository as campaign_repo_module
import backtest.engine as engine_module
from app import create_app
from tests.conftest import FakeCampaignRepository, FakeStrategyRepository

AUTH = {"X-API-Key": config.API_KEY}

_WINDOWS = [
    {"label": "s2", "start": "2025-11-07T00:00:00+00:00", "end": "2026-03-01T00:00:00+00:00"},
    {"label": "s3", "start": "2025-07-16T00:00:00+00:00", "end": "2025-11-07T00:00:00+00:00"},
]
_SPEC = {
    "name": "entry-sweep",
    "windows": _WINDOWS,
    "axes": {"entry_threshold": [3.0, 3.5]},
    "base": {"usd_per_trade": 1000, "scan_window_days": 7, "trade_window_days": 3},
}


@pytest.fixture
def ctx(monkeypatch):
    strat_repo = FakeStrategyRepository()
    camp_repo = FakeCampaignRepository()
    monkeypatch.setattr(repo_module, "_repo", strat_repo)
    monkeypatch.setattr(campaign_repo_module, "_repo", camp_repo)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", "fake")
    client = TestClient(create_app())
    return types.SimpleNamespace(client=client, strat=strat_repo, camp=camp_repo)


def test_requires_auth(ctx):
    assert ctx.client.get("/api/backtest/campaigns").status_code == 401
    assert ctx.client.post("/api/backtest/campaigns", json={"spec": _SPEC}).status_code == 401


def test_create_expands_grid_and_links_members(ctx):
    r = ctx.client.post("/api/backtest/campaigns", json={"spec": _SPEC}, headers=AUTH)
    assert r.status_code == 201, r.text
    body = r.json()
    # 2 entry thresholds × 2 windows = 4 members.
    assert body["strategies_created"] == 4
    campaign = body["campaign"]
    assert campaign["total"] == 4
    assert campaign["status"] == "PENDING"
    # cost_flags are stamped honest-on by default.
    assert campaign["spec"]["cost_flags"] == {
        "per_market_slippage": True, "market_impact": True
    }

    # Every member is PENDING, phase-2, and linked to the campaign, with the window
    # span + axis value threaded in.
    members = ctx.client.get(
        f"/api/backtest/campaigns/{campaign['id']}", headers=AUTH
    ).json()["strategies"]
    assert len(members) == 4
    assert all(m["campaign_id"] == campaign["id"] for m in members)
    assert all(m["phase"] == 2 and m["status"] == "PENDING" for m in members)
    assert {m["entry_threshold"] for m in members} == {3.0, 3.5}
    assert all(m["usd_per_trade"] == 1000 for m in members)  # base applied


def test_malformed_spec_rejected(ctx):
    bad = {"spec": {"name": "x", "axes": {"entry_threshold": [3.0]}}}  # no windows
    assert ctx.client.post("/api/backtest/campaigns", json=bad, headers=AUTH).status_code == 422


def test_unknown_axis_key_rejected(ctx):
    # A typo'd axis key must 422, not silently collapse the grid.
    bad = {"spec": {"name": "x", "windows": _WINDOWS, "axes": {"entry_z": [3.0]}}}
    r = ctx.client.post("/api/backtest/campaigns", json=bad, headers=AUTH)
    assert r.status_code == 422
    assert "entry_z" in r.text


def test_grid_explosion_rejected(ctx):
    big = {"spec": {"name": "x", "windows": [
        {"label": f"w{i}", "start": "2025-01-01T00:00:00+00:00", "end": "2025-02-01T00:00:00+00:00"}
        for i in range(600)
    ]}}
    assert ctx.client.post("/api/backtest/campaigns", json=big, headers=AUTH).status_code == 422


def test_list_and_get_and_404(ctx):
    ctx.client.post("/api/backtest/campaigns", json={"spec": _SPEC}, headers=AUTH)
    lst = ctx.client.get("/api/backtest/campaigns", headers=AUTH).json()
    assert lst["count"] == 1 and lst["campaigns"][0]["name"] == "entry-sweep"
    assert ctx.client.get("/api/backtest/campaigns/nope", headers=AUTH).status_code == 404


def test_delete_detaches_members_not_deletes(ctx):
    created = ctx.client.post(
        "/api/backtest/campaigns", json={"spec": _SPEC}, headers=AUTH
    ).json()
    cid = created["campaign"]["id"]
    member_ids = [
        m["id"]
        for m in ctx.client.get(f"/api/backtest/campaigns/{cid}", headers=AUTH).json()["strategies"]
    ]
    assert len(member_ids) == 4

    d = ctx.client.delete(f"/api/backtest/campaigns/{cid}", headers=AUTH)
    assert d.status_code == 200
    assert ctx.client.get(f"/api/backtest/campaigns/{cid}", headers=AUTH).status_code == 404
    # The member strategies still exist (the campaign delete SET NULLs their FK).
    for sid in member_ids:
        assert ctx.client.get(f"/api/backtest/strategies/{sid}", headers=AUTH).status_code == 200

    assert ctx.client.delete(f"/api/backtest/campaigns/{cid}", headers=AUTH).status_code == 404
