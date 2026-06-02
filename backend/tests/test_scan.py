"""Unit tests for scan state (concurrency guard) and the scan orchestrator."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from scan.orchestrator import run_scan
from scan.state import ScanState
from tests.conftest import (
    FakeDydxClient,
    FakeScanRepository,
    make_cointegrated_series,
    make_flat_series,
    make_independent_walk,
)


# ── ScanState ────────────────────────────────────────────────────────────────


async def test_try_begin_is_single_flight():
    state = ScanState()
    assert await state.try_begin() is True
    # A second claim while running must be refused (the prototype's race fix).
    assert await state.try_begin() is False
    assert state.running is True


async def test_finish_clears_running_and_records_completion():
    state = ScanState()
    await state.try_begin()
    state.finish("done")
    assert state.running is False
    assert state.completed_at is not None
    assert state.phase == 4


async def test_reset_only_when_idle():
    state = ScanState()
    await state.try_begin()
    await state.reset()  # ignored while running
    assert state.running is True
    state.finish("done")
    await state.reset()
    assert state.phase == 0
    assert state.progress_msg == ""


# ── Orchestrator end-to-end (fakes, no network / no DB) ──────────────────────


async def test_run_scan_finds_pair_and_dual_writes(tmp_path, monkeypatch):
    csv = tmp_path / "cointegrated_pairs.csv"
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(csv))

    s1, s2 = make_cointegrated_series()
    noise = make_independent_walk()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "ZZZ-USD": noise})
    repo = FakeScanRepository()

    state = ScanState()
    assert await state.try_begin()
    result = await run_scan(
        client=client, repository=repo, state=state, exchange="dydx", mode="forward_test"
    )

    # The cointegrated pair is found; the independent walk is not paired in.
    assert result["found"] >= 1
    assert state.running is False
    assert state.phase == 4

    rows = repo.store[("dydx", "forward_test")]
    assert len(rows) == result["found"]
    pair = rows[0]
    assert {pair["base_market"], pair["quote_market"]} == {"AAA-USD", "BBB-USD"}
    assert pair["intercept"] != 0.0  # Option-B #1: intercept fitted & stored
    assert 0 < pair["half_life"] <= config.MAX_HALF_LIFE_H
    assert pair["exchange"] == "dydx" and pair["mode"] == "forward_test"

    # CSV half of the dual-write exists and agrees with the DB half.
    assert csv.exists()
    df = pd.read_csv(csv)
    assert len(df) == result["found"]
    assert "intercept" in df.columns


async def test_run_scan_survives_degenerate_market(tmp_path, monkeypatch):
    """A flat/degenerate market must not abort the scan (per-pair isolation)."""
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv"))

    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient(
        {"AAA-USD": s1, "BBB-USD": s2, "FLAT-USD": make_flat_series()}
    )
    repo = FakeScanRepository()
    state = ScanState()
    await state.try_begin()
    result = await run_scan(client=client, repository=repo, state=state)

    # The bad pairs are skipped; the good pair is still found and the scan finishes.
    assert state.phase == 4
    assert state.running is False
    assert state.error is None
    assert result["found"] >= 1
    rows = repo.store[("dydx", "forward_test")]
    assert {"AAA-USD", "BBB-USD"} == {rows[0]["base_market"], rows[0]["quote_market"]}


async def test_run_scan_no_data_finishes_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv")
    )
    client = FakeDydxClient({})  # no markets
    repo = FakeScanRepository()
    state = ScanState()
    await state.try_begin()
    result = await run_scan(client=client, repository=repo, state=state)
    assert result["found"] == 0
    assert state.running is False
    assert "No market data" in state.progress_msg


async def test_run_scan_closes_owned_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv")
    )
    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    repo = FakeScanRepository()
    state = ScanState()
    await state.try_begin()
    # Passing client explicitly means run_scan must NOT close it (caller owns it).
    await run_scan(client=client, repository=repo, state=state)
    assert client.closed is False
