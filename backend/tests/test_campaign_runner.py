"""
Unit tests for the WS3 campaign execution queue (Phase-3 WS3, Slice 2).

Drives the real CampaignRunner against in-memory repos + a fake engine that models
BacktestEngine.run's behaviour (skips a RUNNING row; marks the member terminal). No
real backtests, no DB — the concurrency/resume/cost-flag logic is what's under test.
"""

from __future__ import annotations

import asyncio

import pytest

import config
import backtest.campaign_runner as runner_module
import db.backtest_repository as strat_repo_module
import db.campaign_repository as camp_repo_module
from backtest.campaign_runner import CampaignRunner
from tests.conftest import FakeCampaignRepository, FakeStrategyRepository


class FakeEngine:
    """Models BacktestEngine.run: a RUNNING row is skipped (double-launch guard);
    otherwise the member is marked terminal. Tracks call order + peak concurrency."""

    def __init__(self, repo, outcome="COMPLETED", delay=0.01):
        self.repo = repo
        self.outcome = outcome  # str, or {id: str}, or callable(id)->str
        self.delay = delay
        self.calls: list[str] = []
        self.flag_during: list[bool] = []  # PER_MARKET_SLIPPAGE seen inside run
        self._live = 0
        self.peak = 0

    def _resolve(self, sid, status):
        if callable(self.outcome):
            return self.outcome(sid)
        if isinstance(self.outcome, dict):
            return self.outcome.get(sid, "COMPLETED")
        return self.outcome

    async def run(self, sid):
        row = await self.repo.get(sid)
        if row is None or row["status"] == "RUNNING":
            return  # real engine skips an already-RUNNING row
        self.calls.append(sid)
        self.flag_during.append(config.PER_MARKET_SLIPPAGE)
        await self.repo.update(sid, {"status": "RUNNING"})
        self._live += 1
        self.peak = max(self.peak, self._live)
        await asyncio.sleep(self.delay)
        await self.repo.update(sid, {"status": self._resolve(sid, row["status"])})
        self._live -= 1

    async def request_pause(self, sid):
        await self.repo.update(sid, {"status": "PAUSED"})

    async def request_stop(self, sid):
        await self.repo.update(sid, {"status": "STOPPED"})


@pytest.fixture
def wired(monkeypatch):
    strat = FakeStrategyRepository()
    camp = FakeCampaignRepository()
    monkeypatch.setattr(strat_repo_module, "_repo", strat)
    monkeypatch.setattr(camp_repo_module, "_repo", camp)
    return strat, camp


async def _seed(camp, strat, *, n=3, concurrency=2, cost_flags=None, statuses=None):
    campaign = await camp.create({
        "name": "c", "exchange": "dydx", "data_source": "fake",
        "spec": {"cost_flags": cost_flags or {"per_market_slippage": True, "market_impact": True}},
        "concurrency": concurrency, "total": n,
    })
    for i in range(n):
        st = (statuses or {}).get(i, "PENDING")
        await strat.create({
            "name": f"m{i}", "data_source": "fake", "status": st,
            "campaign_id": campaign["id"],
        })
    return campaign


async def _drain(runner, campaign_id):
    task = runner._tasks[campaign_id]
    await task


async def test_drives_all_members_to_done(wired, monkeypatch):
    strat, camp = wired
    engine = FakeEngine(strat)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)
    campaign = await _seed(camp, strat, n=3)

    runner = CampaignRunner()
    await runner.start(campaign["id"])
    await _drain(runner, campaign["id"])

    members = await strat.list_by_campaign(campaign["id"])
    assert all(m["status"] == "COMPLETED" for m in members)
    assert len(engine.calls) == 3
    done = await camp.get(campaign["id"])
    assert done["status"] == "DONE"
    assert done["completed"] == 3 and done["failed"] == 0
    assert done["ended_at"] is not None


async def test_concurrency_is_bounded(wired, monkeypatch):
    strat, camp = wired
    engine = FakeEngine(strat, delay=0.02)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)
    campaign = await _seed(camp, strat, n=6, concurrency=2)

    runner = CampaignRunner()
    await runner.start(campaign["id"])
    await _drain(runner, campaign["id"])

    assert engine.peak <= 2  # never more than `concurrency` members at once
    assert len(engine.calls) == 6


async def test_cost_flags_set_during_run_then_restored(wired, monkeypatch):
    strat, camp = wired
    monkeypatch.setattr(config, "PER_MARKET_SLIPPAGE", False)
    monkeypatch.setattr(config, "MARKET_IMPACT", False)
    engine = FakeEngine(strat)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)
    campaign = await _seed(camp, strat, n=2,
                           cost_flags={"per_market_slippage": True, "market_impact": True})

    runner = CampaignRunner()
    await runner.start(campaign["id"])
    await _drain(runner, campaign["id"])

    # The flag was ON while members ran…
    assert engine.flag_during and all(engine.flag_during)
    # …and restored to the saved value afterwards.
    assert config.PER_MARKET_SLIPPAGE is False
    assert config.MARKET_IMPACT is False


async def test_failed_member_counted_campaign_still_done(wired, monkeypatch):
    strat, camp = wired
    campaign = await _seed(camp, strat, n=3)
    members = await strat.list_by_campaign(campaign["id"])
    fail_id = members[1]["id"]
    engine = FakeEngine(strat, outcome={fail_id: "FAILED"})
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)

    runner = CampaignRunner()
    await runner.start(campaign["id"])
    await _drain(runner, campaign["id"])

    done = await camp.get(campaign["id"])
    assert done["status"] == "DONE"
    assert done["completed"] == 2 and done["failed"] == 1


async def test_resume_normalises_interrupted_running_member(wired, monkeypatch):
    strat, camp = wired
    # m0 was left RUNNING with a cursor by a crash; without normalisation the fake
    # engine (like the real one) would SKIP it and it'd never complete.
    campaign = await _seed(camp, strat, n=2, statuses={0: "RUNNING"})
    members = await strat.list_by_campaign(campaign["id"])
    await strat.update(members[0]["id"], {"processed_windows": 2})
    engine = FakeEngine(strat)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)

    runner = CampaignRunner()
    await runner.start(campaign["id"])
    await _drain(runner, campaign["id"])

    after = await strat.list_by_campaign(campaign["id"])
    assert all(m["status"] == "COMPLETED" for m in after)  # the RUNNING one got re-driven
    assert (await camp.get(campaign["id"]))["status"] == "DONE"


async def test_stop_marks_stopped_and_signals_running_member(wired, monkeypatch):
    strat, camp = wired
    campaign = await _seed(camp, strat, n=2, statuses={0: "RUNNING"})
    engine = FakeEngine(strat)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)

    runner = CampaignRunner()
    res = await runner.request_stop(campaign["id"])
    assert res["status"] == "STOPPED"
    members = await strat.list_by_campaign(campaign["id"])
    # The in-flight (RUNNING) member was signalled to stop.
    assert any(m["status"] == "STOPPED" for m in members)


async def test_pause_marks_paused_and_signals_running_member(wired, monkeypatch):
    strat, camp = wired
    campaign = await _seed(camp, strat, n=2, statuses={0: "RUNNING"})
    engine = FakeEngine(strat)
    monkeypatch.setattr(runner_module, "get_backtest_engine", lambda: engine)

    runner = CampaignRunner()
    res = await runner.request_pause(campaign["id"])
    assert res["status"] == "PAUSED"
    members = await strat.list_by_campaign(campaign["id"])
    assert any(m["status"] == "PAUSED" for m in members)
