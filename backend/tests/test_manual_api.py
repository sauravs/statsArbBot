"""
Integration tests for the manual-trading HTTP surface (Phase 4, PRD F4).

Real FastAPI app + mocked dYdX client + in-memory repositories. Exercises the
record → list → close lifecycle and the error paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import db.scan_repository as scan_repo_module
import manual.repository as manual_repo_module
from app import create_app
from tests.conftest import (
    FakeDydxClient,
    FakeManualTradeRepository,
    FakeScanRepository,
    make_cointegrated_series,
    make_independent_walk,
)

AUTH = {"X-API-Key": config.API_KEY}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from scan.state import SCAN_STATE

    SCAN_STATE.__init__()

    monkeypatch.setattr(scan_repo_module, "_repo", FakeScanRepository())
    monkeypatch.setattr(manual_repo_module, "_repo", FakeManualTradeRepository())

    s1, s2 = make_cointegrated_series()
    noise = make_independent_walk()
    fake_client = FakeDydxClient({"AAA-USD": s1, "BBB-USD": s2, "ZZZ-USD": noise})
    monkeypatch.setattr(
        "exchanges.dydx.client.DydxDataClient", lambda *a, **k: fake_client
    )
    monkeypatch.setattr(config, "COINTEGRATED_PAIRS_CSV", str(tmp_path / "pairs.csv"))
    return TestClient(create_app())


def _scan(client):
    r = client.post("/api/scan/start", json={"quick": True}, headers=AUTH)
    assert r.status_code == 202
    assert client.get("/api/scan/status", headers=AUTH).json()["pairs_found"] >= 1


def _record(client, base="AAA-USD", quote="BBB-USD", c1=100.0, c2=100.0):
    return client.post(
        "/api/manual/record",
        json={
            "base_market": base,
            "quote_market": quote,
            "capital_leg1_usd": c1,
            "capital_leg2_usd": c2,
        },
        headers=AUTH,
    )


def test_manual_requires_auth(client):
    assert client.get("/api/manual").status_code == 401
    assert client.post("/api/manual/record", json={
        "base_market": "AAA-USD", "quote_market": "BBB-USD",
        "capital_leg1_usd": 100, "capital_leg2_usd": 100,
    }).status_code == 401
    assert client.post("/api/manual/x/close", json={
        "exit_price_leg1": 1, "exit_price_leg2": 1,
    }).status_code == 401


def test_record_then_list_then_close(client):
    _scan(client)

    # Record.
    r = _record(client, c1=100.0, c2=100.0)
    assert r.status_code == 201, r.text
    trade = r.json()
    assert trade["status"] == "OPEN"
    assert trade["base_market"] == "AAA-USD"
    assert trade["entry_price_leg1"] > 0 and trade["entry_price_leg2"] > 0
    assert trade["pnl"] is None and trade["closed_at"] is None
    tid = trade["id"]

    # List shows the open trade.
    lst = client.get("/api/manual", headers=AUTH).json()
    assert lst["count"] == 1
    assert lst["trades"][0]["id"] == tid

    # Close with exit prices → P&L computed, status CLOSED.
    e1 = trade["entry_price_leg1"] * 1.1
    e2 = trade["entry_price_leg2"] * 0.9
    closed = client.post(
        f"/api/manual/{tid}/close",
        json={"exit_price_leg1": e1, "exit_price_leg2": e2},
        headers=AUTH,
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "CLOSED"
    assert body["closed_at"] is not None
    assert body["pnl"] is not None
    assert "pnl_breakdown" in body
    assert body["pnl"] == pytest.approx(
        body["pnl_breakdown"]["pnl_leg1"] + body["pnl_breakdown"]["pnl_leg2"]
    )


# --- issue #147: p-value + half-life re-validation at manual entry -----------


def test_record_persists_fresh_pvalue_and_half_life(client):
    """The fresh re-check runs at record time and its p-value + half-life are
    persisted on the trade (the scan's stored values may be stale)."""
    _scan(client)
    trade = _record(client).json()
    assert trade["p_value"] is not None and 0.0 <= trade["p_value"] < 0.05
    assert trade["half_life"] is not None and trade["half_life"] > 0


def test_record_blocks_when_half_life_exceeds_threshold(client):
    """A stricter-than-scan half-life cap hard-blocks (422) a pair the scan
    admitted — the fresh half-life is outside the operator's entry threshold."""
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD", "quote_market": "BBB-USD",
            "capital_leg1_usd": 100, "capital_leg2_usd": 100,
            "max_half_life_h": 0.001,  # far below the pair's ~1.4h half-life
        },
        headers=AUTH,
    )
    assert r.status_code == 422, r.text
    assert "half-life" in r.json()["detail"].lower()


def test_record_allows_looser_pvalue_override(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD", "quote_market": "BBB-USD",
            "capital_leg1_usd": 100, "capital_leg2_usd": 100,
            "pvalue_max": 0.20,
        },
        headers=AUTH,
    )
    assert r.status_code == 201, r.text


def test_record_rejects_out_of_range_thresholds(client):
    _scan(client)
    for bad in ({"pvalue_max": 1.5}, {"pvalue_max": 0}, {"max_half_life_h": 0}):
        r = client.post(
            "/api/manual/record",
            json={
                "base_market": "AAA-USD", "quote_market": "BBB-USD",
                "capital_leg1_usd": 100, "capital_leg2_usd": 100, **bad,
            },
            headers=AUTH,
        )
        assert r.status_code == 422, (bad, r.text)


def test_record_forwards_thresholds_to_fresh_analysis(client, monkeypatch):
    """The request's thresholds (and the scan-depth page count) are what the
    fresh re-check is actually run against."""
    import routers.manual as manual_router
    from marketdata.pair_series import current_pair_analysis as real_analysis

    captured: dict = {}

    async def spy(*args, **kwargs):
        captured.update(kwargs)
        return await real_analysis(*args, **kwargs)

    monkeypatch.setattr(manual_router, "current_pair_analysis", spy)
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD", "quote_market": "BBB-USD",
            "capital_leg1_usd": 100, "capital_leg2_usd": 100,
            "pvalue_max": 0.123, "max_half_life_h": 48.0,
        },
        headers=AUTH,
    )
    assert r.status_code == 201, r.text
    assert captured["pvalue_max"] == 0.123
    assert captured["max_half_life"] == 48.0
    assert captured["num_pages"] == config.MANUAL_FILTER_PAGES


def test_record_blocks_on_failed_cointegration_with_pvalue_detail(client, monkeypatch):
    """A pair whose cointegration has decayed on fresh data is hard-blocked with
    a p-value reason in the detail — the drift the stale scan wouldn't catch."""
    import routers.manual as manual_router
    from statcore import PairAnalysis

    async def failing(*args, **kwargs):
        return PairAnalysis(
            hedge_ratio=2.0, intercept=5.0, p_value=0.42,
            t_statistic=-1.0, critical_value_5pct=-3.0,
            half_life=10.0, zero_crossings=5, passes_filter=False,
        )

    monkeypatch.setattr(manual_router, "current_pair_analysis", failing)
    _scan(client)
    r = _record(client)
    assert r.status_code == 422, r.text
    assert "p-value" in r.json()["detail"].lower()


def test_record_blocks_when_fresh_history_unusable(client, monkeypatch):
    """If fresh candles can't re-validate the pair (no usable history), the
    record is rejected rather than trusting the stale scan."""
    import routers.manual as manual_router

    async def none_analysis(*args, **kwargs):
        return None

    monkeypatch.setattr(manual_router, "current_pair_analysis", none_analysis)
    _scan(client)
    r = _record(client)
    assert r.status_code == 422, r.text


def test_record_uses_single_page_fast_path(client, monkeypatch):
    """Issue #54: recording fetches only one candle page per leg (fast path),
    not the full paginated history — so a live record completes in seconds."""
    import routers.manual as manual_router
    from marketdata.pair_series import current_pair_snapshot as real_snapshot

    captured: dict = {}

    async def spy(*args, **kwargs):
        captured["num_pages"] = kwargs.get("num_pages")
        return await real_snapshot(*args, **kwargs)

    monkeypatch.setattr(manual_router, "current_pair_snapshot", spy)

    _scan(client)
    r = _record(client)
    assert r.status_code == 201, r.text
    assert captured["num_pages"] == 1


def test_record_unknown_pair_404(client):
    _scan(client)
    r = _record(client, base="BBB-USD", quote="AAA-USD")  # reversed = not scanned
    assert r.status_code == 404


def test_record_before_scan_404(client):
    assert _record(client).status_code == 404


def test_record_rejects_nonpositive_capital(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 0,
            "capital_leg2_usd": 100,
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_double_close_returns_409(client):
    _scan(client)
    tid = _record(client).json()["id"]
    body = {"exit_price_leg1": 10.0, "exit_price_leg2": 10.0}
    assert client.post(f"/api/manual/{tid}/close", json=body, headers=AUTH).status_code == 200
    assert client.post(f"/api/manual/{tid}/close", json=body, headers=AUTH).status_code == 409


def test_record_rejects_unknown_exchange(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 100,
            "capital_leg2_usd": 100,
            "exchange": "kraken",
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_list_rejects_unknown_mode(client):
    r = client.get("/api/manual", params={"mode": "bogus"}, headers=AUTH)
    assert r.status_code == 422


def test_close_unknown_trade_404(client):
    r = client.post(
        "/api/manual/nope/close",
        json={"exit_price_leg1": 10.0, "exit_price_leg2": 10.0},
        headers=AUTH,
    )
    assert r.status_code == 404


# --- issue #55: hard delete a manual trade (OPEN or CLOSED) -------------------


def test_delete_requires_auth(client):
    assert client.delete("/api/manual/some-id").status_code == 401


def test_delete_open_trade(client):
    _scan(client)
    tid = _record(client).json()["id"]
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 1

    r = client.delete(f"/api/manual/{tid}", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": tid}
    # Gone from the list and the counts.
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 0
    # A second delete now 404s (the row is permanently removed).
    assert client.delete(f"/api/manual/{tid}", headers=AUTH).status_code == 404


def test_delete_closed_trade(client):
    _scan(client)
    trade = _record(client).json()
    tid = trade["id"]
    client.post(
        f"/api/manual/{tid}/close",
        json={"exit_price_leg1": 10.0, "exit_price_leg2": 10.0},
        headers=AUTH,
    )
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 1

    r = client.delete(f"/api/manual/{tid}", headers=AUTH)
    assert r.status_code == 200, r.text
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 0


def test_delete_unknown_trade_404(client):
    assert client.delete("/api/manual/nope", headers=AUTH).status_code == 404


# --- issue #37 PR-2: current prices + portfolio -----------------------------


def test_pair_prices_after_scan(client):
    _scan(client)
    r = client.get("/api/pairs/prices", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    # Both legs of the scanned AAA/BBB pair are priced with positive floats.
    assert body["prices"]["AAA-USD"] > 0
    assert body["prices"]["BBB-USD"] > 0


def test_pair_prices_before_scan_empty(client):
    r = client.get("/api/pairs/prices", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"prices": {}, "error": None}


def test_portfolio_open_trade_marked_to_market(client):
    _scan(client)
    _record(client, c1=120.0, c2=80.0)

    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p["error"] is None
    assert p["open_count"] == 1 and p["closed_count"] == 0
    assert p["allocated_capital"] == pytest.approx(200.0)  # 120 + 80
    assert p["realized_pnl"] == pytest.approx(0.0)
    # Marked to market at the current close, which equals the entry close for the
    # static fake series → ~0 unrealized P&L (but priced, so not None).
    assert p["unrealized_pnl"] == pytest.approx(0.0, abs=1e-6)


def test_portfolio_realized_after_close(client):
    _scan(client)
    trade = _record(client, c1=100.0, c2=100.0).json()
    closed = client.post(
        f"/api/manual/{trade['id']}/close",
        json={
            "exit_price_leg1": trade["entry_price_leg1"] * 1.1,
            "exit_price_leg2": trade["entry_price_leg2"] * 0.9,
        },
        headers=AUTH,
    ).json()

    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p["open_count"] == 0 and p["closed_count"] == 1
    assert p["allocated_capital"] == pytest.approx(0.0)  # no OPEN trades
    assert p["unrealized_pnl"] is None  # nothing to mark to market
    assert p["realized_pnl"] == pytest.approx(closed["pnl"])


def test_portfolio_empty(client):
    p = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert p == {
        "allocated_capital": 0.0,
        "unrealized_pnl": None,
        "realized_pnl": 0.0,
        "open_count": 0,
        "closed_count": 0,
        "error": None,
    }


def test_portfolio_rejects_unknown_mode(client):
    r = client.get("/api/manual/portfolio", params={"mode": "bogus"}, headers=AUTH)
    assert r.status_code == 422


# --- issue #43 follow-up: manual trades are scoped to the active data source ---


def test_trade_stamped_with_active_data_source(client):
    # The scan/record fixture runs against the live (dydx) source, so the trade
    # is stamped with whatever source is active at record time.
    _scan(client)
    trade = _record(client).json()
    assert trade["data_source"] == config.SCAN_DATA_SOURCE


def test_list_and_portfolio_hide_other_source_trades(client, monkeypatch):
    _scan(client)
    _record(client, c1=150.0, c2=150.0)  # stamped with the active source
    recorded_source = config.SCAN_DATA_SOURCE
    other = "fake" if recorded_source != "fake" else "dydx"

    assert client.get("/api/manual", headers=AUTH).json()["count"] == 1
    assert client.get("/api/manual/portfolio", headers=AUTH).json()["open_count"] == 1

    # Switch the active source → the trade (recorded under the other) is hidden,
    # not deleted.
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", other)
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 0
    portfolio = client.get("/api/manual/portfolio", headers=AUTH).json()
    assert portfolio["open_count"] == 0
    assert portfolio["allocated_capital"] == pytest.approx(0.0)

    # Switch back → it reappears.
    monkeypatch.setattr(config, "SCAN_DATA_SOURCE", recorded_source)
    assert client.get("/api/manual", headers=AUTH).json()["count"] == 1


# --- realised-execution capture: actual fills + reference prices --------------
# The backtest charges a *modelled* slippage_pct per fill; the true cost of a
# market order is only knowable from real fills. These tests pin the storage
# contract that makes realised slippage computable per leg.


def test_record_stores_actual_entry_fills(client):
    """Optional fill prices round-trip, paired with the reference prices."""
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 100.0,
            "capital_leg2_usd": 100.0,
            "fill_price_leg1": 123.45,
            "fill_price_leg2": 67.89,
        },
        headers=AUTH,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["fill_price_leg1"] == pytest.approx(123.45)
    assert t["fill_price_leg2"] == pytest.approx(67.89)
    # The server-captured reference is kept alongside, so realised entry
    # slippage = (fill - reference) / reference is computable.
    assert t["entry_price_leg1"] > 0 and t["entry_price_leg2"] > 0


def test_record_fills_are_optional(client):
    """Omitting the fills is valid — they simply stay None (unmeasurable)."""
    _scan(client)
    t = _record(client).json()
    assert t["fill_price_leg1"] is None
    assert t["fill_price_leg2"] is None


def test_record_rejects_non_positive_fill(client):
    _scan(client)
    r = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 100.0,
            "capital_leg2_usd": 100.0,
            "fill_price_leg1": 0,
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_close_captures_exit_reference_prices(client):
    """Closing stamps the server-side reference to pair with the actual exit fill."""
    _scan(client)
    trade = _record(client).json()
    closed = client.post(
        f"/api/manual/{trade['id']}/close",
        json={"exit_price_leg1": 10.0, "exit_price_leg2": 20.0},
        headers=AUTH,
    ).json()
    # Operator's actual fills stored as given...
    assert closed["exit_price_leg1"] == pytest.approx(10.0)
    assert closed["exit_price_leg2"] == pytest.approx(20.0)
    # ...and the reference captured server-side, so exit slippage is computable.
    assert closed["exit_ref_price_leg1"] is not None
    assert closed["exit_ref_price_leg2"] is not None
    assert closed["exit_ref_price_leg1"] > 0


def test_pnl_uses_actual_fill_not_reference(client):
    """P&L is booked against what was actually paid, including entry slippage.

    Two identical trades differing only in the recorded entry fill must produce
    different P&L — otherwise the stored result silently assumes a fill at the
    reference price and understates the true cost of execution.
    """
    _scan(client)
    ref = _record(client).json()
    # Same pair/size, but a materially worse recorded entry fill on leg 1.
    worse = client.post(
        "/api/manual/record",
        json={
            "base_market": "AAA-USD",
            "quote_market": "BBB-USD",
            "capital_leg1_usd": 100.0,
            "capital_leg2_usd": 100.0,
            "fill_price_leg1": ref["entry_price_leg1"] * 1.05,
            "fill_price_leg2": ref["entry_price_leg2"],
        },
        headers=AUTH,
    ).json()

    exits = {
        "exit_price_leg1": ref["entry_price_leg1"] * 1.10,
        "exit_price_leg2": ref["entry_price_leg2"] * 0.90,
    }
    pnl_ref = client.post(
        f"/api/manual/{ref['id']}/close", json=exits, headers=AUTH
    ).json()["pnl"]
    pnl_worse = client.post(
        f"/api/manual/{worse['id']}/close", json=exits, headers=AUTH
    ).json()["pnl"]

    assert pnl_ref != pytest.approx(pnl_worse)
