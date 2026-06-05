"""
Tests for UI-configurable Option-B signal thresholds (issue #74).

  GET  /api/system/thresholds  — the active entry/exit/stop.
  POST /api/system/thresholds  — set them app-wide at runtime (validated,
                                 ordering exit < entry < stop) + persist to
                                 BotConfigHistory so they survive a restart.

Covers the pure ``config.set_signal_thresholds`` validator, the router (real app
+ in-memory bot-config repo), persistence wiring, and the startup re-apply
(``load_persisted_thresholds``). The fixture saves/restores the module-level
threshold globals so a set can't leak between tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.bot_config_repository as bcr_module
from app import create_app
from db.bot_config_repository import load_persisted_thresholds

AUTH = {"X-API-Key": config.API_KEY}


class FakeBotConfigRepository:
    """In-memory stand-in: an append-only list, latest matching row wins."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.fail = False  # flip to simulate a persistence hiccup

    async def save_thresholds(self, entry, exit, stop, *, exchange, mode) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.rows.append(
            {"entry": entry, "exit": exit, "stop": stop, "exchange": exchange, "mode": mode}
        )

    async def get_latest_thresholds(self, *, exchange, mode):
        for r in reversed(self.rows):
            if r["exchange"] == exchange and r["mode"] == mode:
                return {"entry": r["entry"], "exit": r["exit"], "stop": r["stop"]}
        return None


@pytest.fixture
def repo(monkeypatch):
    fake = FakeBotConfigRepository()
    monkeypatch.setattr(bcr_module, "_repo", fake)
    # Save/restore the globals so a runtime set doesn't bleed across tests.
    saved = config.get_signal_thresholds()
    config.set_signal_thresholds(1.5, 0.5, 4.0)
    yield fake
    config.set_signal_thresholds(saved["entry"], saved["exit"], saved["stop"])


@pytest.fixture
def client(repo):
    return TestClient(create_app())


# ── pure validator ───────────────────────────────────────────────────────────


def test_set_signal_thresholds_applies_globals(repo):
    config.set_signal_thresholds(2.0, 0.4, 5.0)
    assert (config.ZSCORE_THRESH, config.EXIT_ZSCORE, config.STOP_LOSS_ZSCORE) == (
        2.0,
        0.4,
        5.0,
    )
    assert config.get_signal_thresholds() == {"entry": 2.0, "exit": 0.4, "stop": 5.0}


@pytest.mark.parametrize(
    "entry,exit,stop",
    [
        (1.0, 1.5, 4.0),  # exit >= entry
        (4.0, 0.5, 4.0),  # entry >= stop
        (0.4, 0.3, 4.0),  # entry below min
        (5.0, 0.5, 6.0),  # entry above max
        (1.5, 0.0, 4.0),  # exit not strictly > 0
        (1.5, 0.5, 0.9),  # stop below min
        (1.5, 0.5, 11.0),  # stop above max
        (float("nan"), 0.5, 4.0),  # non-finite
    ],
)
def test_set_signal_thresholds_rejects_invalid(repo, entry, exit, stop):
    with pytest.raises(ValueError):
        config.set_signal_thresholds(entry, exit, stop)


# ── router ───────────────────────────────────────────────────────────────────


def test_get_requires_auth(client):
    assert client.get("/api/system/thresholds").status_code == 401


def test_get_returns_active_thresholds(client):
    assert client.get("/api/system/thresholds", headers=AUTH).json() == {
        "entry": 1.5,
        "exit": 0.5,
        "stop": 4.0,
    }


def test_set_requires_auth(client):
    r = client.post("/api/system/thresholds", json={"entry": 2, "exit": 0.4, "stop": 5})
    assert r.status_code == 401


def test_set_updates_config_persists_and_reflects(client, repo):
    r = client.post(
        "/api/system/thresholds",
        json={"entry": 2.0, "exit": 0.4, "stop": 5.0},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"entry": 2.0, "exit": 0.4, "stop": 5.0, "persisted": True}
    # Global mutated → call-time readers (chart / strategy) pick it up.
    assert config.ZSCORE_THRESH == 2.0
    # Persisted to BotConfigHistory under the default scope.
    assert repo.rows[-1] == {
        "entry": 2.0,
        "exit": 0.4,
        "stop": 5.0,
        "exchange": config.DEFAULT_EXCHANGE,
        "mode": config.DEFAULT_MODE,
    }
    # GET now reflects the new values.
    assert client.get("/api/system/thresholds", headers=AUTH).json()["entry"] == 2.0


def test_set_rejects_bad_ordering(client):
    r = client.post(
        "/api/system/thresholds",
        json={"entry": 1.0, "exit": 1.5, "stop": 4.0},
        headers=AUTH,
    )
    assert r.status_code == 422
    assert "exit < entry < stop" in r.json()["detail"]
    # Rejected set leaves the defaults untouched.
    assert config.ZSCORE_THRESH == 1.5


def test_set_rejects_out_of_bounds(client):
    r = client.post(
        "/api/system/thresholds",
        json={"entry": 9.0, "exit": 0.5, "stop": 10.0},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_persist_failure_keeps_runtime_value(client, repo):
    repo.fail = True
    r = client.post(
        "/api/system/thresholds",
        json={"entry": 2.0, "exit": 0.4, "stop": 5.0},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["persisted"] is False
    # Runtime change still took effect despite the DB hiccup.
    assert config.ZSCORE_THRESH == 2.0


# ── startup re-apply ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_persisted_thresholds_applies_saved(repo):
    await repo.save_thresholds(
        2.5, 0.3, 6.0, exchange=config.DEFAULT_EXCHANGE, mode=config.DEFAULT_MODE
    )
    await load_persisted_thresholds()
    assert config.get_signal_thresholds() == {"entry": 2.5, "exit": 0.3, "stop": 6.0}


@pytest.mark.asyncio
async def test_load_persisted_thresholds_noop_when_absent(repo):
    await load_persisted_thresholds()  # no saved row
    assert config.get_signal_thresholds() == {"entry": 1.5, "exit": 0.5, "stop": 4.0}
