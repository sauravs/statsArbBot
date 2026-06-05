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


async def test_run_scan_surfaces_dropped_markets(tmp_path, monkeypatch):
    """Markets excluded from the matrix are reported in the result + state (#6/#7)."""
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv"))

    s1, s2 = make_cointegrated_series(n=120)
    # PARTIAL covers only the first half of the window → dropped as "misaligned".
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "PARTIAL-USD": s1[:60]})
    repo = FakeScanRepository()
    state = ScanState()
    await state.try_begin()
    result = await run_scan(client=client, repository=repo, state=state)

    assert result["markets_dropped"] == 1
    assert result["dropped_by_reason"].get("misaligned") == 1
    assert state.markets_dropped == 1
    assert state.snapshot()["markets_dropped"] == 1
    assert state.snapshot()["dropped_by_reason"].get("misaligned") == 1


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


# ── Stop Scan (issue #59) ────────────────────────────────────────────────────


async def test_request_stop_only_when_running():
    state = ScanState()
    # Idle → nothing to stop.
    assert await state.request_stop() is False
    await state.try_begin()
    assert state.stop_requested is False  # try_begin clears the flag
    assert await state.request_stop() is True
    assert state.stop_requested is True
    assert "Stopping" in state.progress_msg


async def test_run_scan_stopped_during_fetch_writes_empty(tmp_path, monkeypatch):
    """A stop during the market-fetch phase aborts promptly and reflects 0 pairs."""
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv"))

    s1, s2 = make_cointegrated_series()
    client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2})
    repo = FakeScanRepository()
    state = ScanState()
    await state.try_begin()
    state.stop_requested = True  # flag a stop before the fetch callbacks fire

    result = await run_scan(
        client=client, repository=repo, state=state, exchange="dydx", mode="forward_test"
    )

    assert result["stopped"] is True
    assert result["found"] == 0
    assert state.running is False and state.stopped is True
    assert "Stopped during market fetch" in state.progress_msg
    # The (empty) partial result replaced the table.
    assert repo.store[("dydx", "forward_test")] == []


class _StopAfterFirstChunk(ScanState):
    """Flips stop_requested True once the first pair-chunk has been tested, so the
    scan halts at the second chunk's checkpoint (a deterministic partial stop)."""

    def update_pairs(self, tested, total, found):
        super().update_pairs(tested, total, found)
        if tested > 0:  # the pre-loop call has tested=0 — don't stop before it starts
            self.stop_requested = True


async def test_run_scan_stopped_during_pair_testing_writes_partial(tmp_path, monkeypatch):
    """A stop mid-pair-testing persists the survivors found so far (partial)."""
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "out.csv"))

    # 21 markets → C(21,2)=210 pairs > _CHUNK_SIZE (200), so there are 2 chunks.
    # AAA/BBB are cointegrated and ordered first, so their pair is in chunk 1.
    s1, s2 = make_cointegrated_series()
    series = {"AAA-USD": s1, "BBB-USD": s2}
    for i in range(19):
        series[f"N{i:02d}-USD"] = make_independent_walk(seed=1000 + i)

    client = FakeDydxClient(series)
    repo = FakeScanRepository()
    state = _StopAfterFirstChunk()
    await state.try_begin()

    result = await run_scan(
        client=client, repository=repo, state=state, exchange="dydx", mode="forward_test"
    )

    assert result["stopped"] is True
    assert state.stopped is True and state.running is False
    # Stopped after the first chunk: fewer than all pairs were tested.
    assert result["tested"] == 200
    assert result["tested"] < state.total_pairs  # 200 < 210
    assert "Stopped —" in state.progress_msg
    # The survivors from the tested chunk are persisted (incl. the AAA/BBB pair).
    rows = repo.store[("dydx", "forward_test")]
    assert len(rows) == result["found"] >= 1
    assert any(
        {r["base_market"], r["quote_market"]} == {"AAA-USD", "BBB-USD"} for r in rows
    )


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
