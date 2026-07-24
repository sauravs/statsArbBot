"""
Walk-forward backtest endpoints (PRD F8.3/F8.4). The control surface the Phase-8 UI
(backtest page, strategy comparison, create strategy, reports viewer) consumes.

  POST   /api/backtest/strategies              — create a strategy (CRUD).
  GET    /api/backtest/strategies              — list strategies, ranked by net P&L.
  GET    /api/backtest/strategies/{id}         — one strategy + its latest result.
  PUT    /api/backtest/strategies/{id}         — edit a strategy's parameters.
  DELETE /api/backtest/strategies/{id}         — delete a strategy (re-ranks the rest).
  POST   /api/backtest/strategies/{id}/run     — run (or resume) the walk-forward sweep.
  POST   /api/backtest/strategies/{id}/pause   — pause a running sweep (resumable).
  POST   /api/backtest/strategies/{id}/stop    — stop a running sweep (terminal).
  GET    /api/backtest/strategies/{id}/report  — the generated markdown report.
  POST   /api/backtest/seed-defaults           — seed the S1–S4 baseline strategies.

The sweep runs as a background task; the POST returns the RUNNING row and the UI
polls the detail endpoint for progress → COMPLETED. Thresholds and window lengths
are bounded at this trust boundary (as in the sim/ff routers).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
from auth import require_api_key
from backtest.engine import StrategyNotFound, get_backtest_engine
from exchanges import EXCHANGE_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", dependencies=[Depends(require_api_key)])


def _validate_exchange(exchange: str) -> None:
    if exchange not in EXCHANGE_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown exchange '{exchange}'.")
    if not EXCHANGE_REGISTRY[exchange].integrated:
        raise HTTPException(status_code=422, detail=f"Exchange '{exchange}' is not integrated.")


def _guard_db(exc: Exception) -> HTTPException:
    logger.error("backtest engine DB error: %s", exc)
    return HTTPException(status_code=503, detail="Backtest datastore unavailable.")


class StrategyBody(BaseModel):
    exchange: str = config.DEFAULT_EXCHANGE
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    scan_window_days: int = Field(default=90, ge=1, le=365)
    trade_window_days: int = Field(default=30, ge=1, le=365)
    zscore_window: int = Field(default=config.ZSCORE_WINDOW, ge=3, le=500)
    entry_threshold: float = Field(default=config.ZSCORE_THRESH, ge=0.5, le=4.0)
    exit_threshold: float = Field(default=config.EXIT_ZSCORE, gt=0.0, le=2.0)
    stop_threshold: float = Field(default=config.STOP_LOSS_ZSCORE, ge=1.0, le=10.0)
    pvalue_max: float = Field(default=config.PVALUE_MAX, gt=0.0, le=1.0)
    max_half_life_h: float = Field(default=config.MAX_HALF_LIFE_H, gt=0.0, le=1000.0)
    start_time: datetime | None = None
    end_time: datetime | None = None
    starting_capital: float = Field(default=10_000.0, gt=0)
    usd_per_trade: float = Field(default=config.USD_PER_TRADE, gt=0)
    max_active_pairs: int | None = Field(default=None, ge=1, le=100)
    slippage_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    taker_fee_pct: float = Field(default=0.05, ge=0.0, le=5.0)
    funding_freq_h: int = Field(default=1, ge=1, le=24)


class StrategyUpdateBody(BaseModel):
    """Editable fields (CRUD); omit a field to leave it unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    scan_window_days: int | None = Field(default=None, ge=1, le=365)
    trade_window_days: int | None = Field(default=None, ge=1, le=365)
    zscore_window: int | None = Field(default=None, ge=3, le=500)
    entry_threshold: float | None = Field(default=None, ge=0.5, le=4.0)
    exit_threshold: float | None = Field(default=None, gt=0.0, le=2.0)
    stop_threshold: float | None = Field(default=None, ge=1.0, le=10.0)
    pvalue_max: float | None = Field(default=None, gt=0.0, le=1.0)
    max_half_life_h: float | None = Field(default=None, gt=0.0, le=1000.0)
    start_time: datetime | None = None
    end_time: datetime | None = None
    starting_capital: float | None = Field(default=None, gt=0)
    usd_per_trade: float | None = Field(default=None, gt=0)
    max_active_pairs: int | None = Field(default=None, ge=1, le=100)
    slippage_pct: float | None = Field(default=None, ge=0.0, le=5.0)
    taker_fee_pct: float | None = Field(default=None, ge=0.0, le=5.0)
    funding_freq_h: int | None = Field(default=None, ge=1, le=24)


def _normalise_span(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and start >= end:
        raise HTTPException(status_code=422, detail="start_time must be before end_time.")


def _parse_dt(value) -> datetime | None:
    """Coerce a stored ISO-string timestamp (or None) back to a datetime."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@router.post("/strategies", status_code=201)
async def create_strategy(body: StrategyBody) -> dict:
    # The venue follows the active data source (e.g. hyperliquid when the source is
    # HL) so the backtest engine reads that venue's cache; otherwise an HL-mode
    # strategy would default to dydx and read an empty/ wrong cache. The UI selects
    # the venue via the data-source switch, not the strategy form (this phase).
    exchange = config.active_exchange()
    _validate_exchange(exchange)
    _normalise_span(body.start_time, body.end_time)
    params = body.model_dump()
    params["exchange"] = exchange
    params["status"] = "PENDING"
    # Stamp the active market-data source so the list stays scoped to demo/live
    # (issue #98), mirroring how manual trades are stamped on record.
    params["data_source"] = config.SCAN_DATA_SOURCE
    try:
        return await get_backtest_engine().create(params)
    except Exception as exc:
        raise _guard_db(exc)


@router.get("/strategies")
async def list_strategies() -> dict:
    try:
        rows = await get_backtest_engine().list()
    except Exception as exc:
        raise _guard_db(exc)
    return {"strategies": rows, "count": len(rows)}


@router.get("/significance")
async def strategy_significance() -> dict:
    """Deflated-Sharpe significance across the saved-strategy search (gate B3).

    Returns ``{n_trials, trial_sr_variance, dsr: {id: value}}`` — a per-config DSR that
    corrects for the size of the search, so the UI can badge which configs survive
    multiple-testing correction (DSR > 0.95). See ``stats.significance``.
    """
    from stats.significance import compute_leaderboard_dsr

    try:
        rows = await get_backtest_engine().list()
    except Exception as exc:
        raise _guard_db(exc)
    return compute_leaderboard_dsr(rows)


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict:
    try:
        row = await get_backtest_engine().get(strategy_id)
    except Exception as exc:
        raise _guard_db(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return row


@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, body: StrategyUpdateBody) -> dict:
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    try:
        engine = get_backtest_engine()
        existing = await engine.get(strategy_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Strategy not found.")
        # A RUNNING or PAUSED strategy is mid-sweep: editing window lengths / span /
        # capital would desync the persisted resume cursor (processed_windows) from a
        # freshly-recomputed window list and break the net_pnl identity. Require a
        # terminal/idle state to edit.
        if existing["status"] in ("RUNNING", "PAUSED"):
            raise HTTPException(
                status_code=409,
                detail="A running or paused strategy cannot be edited — stop it first.",
            )
        # Validate the EFFECTIVE span (a partial edit of only start or only end must
        # still be checked against the stored counterpart).
        _normalise_span(
            data.get("start_time", _parse_dt(existing["start_time"])),
            data.get("end_time", _parse_dt(existing["end_time"])),
        )
        updated = await engine.update(strategy_id, data) if data else existing
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)
    if updated is None:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return updated


@router.delete("/strategies/{strategy_id}", status_code=200)
async def delete_strategy(strategy_id: str) -> dict:
    try:
        engine = get_backtest_engine()
        existing = await engine.get(strategy_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Strategy not found.")
        if existing["status"] == "RUNNING":
            raise HTTPException(status_code=409, detail="A running strategy cannot be deleted.")
        await engine.delete(strategy_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)
    return {"deleted": strategy_id}


@router.post("/strategies/{strategy_id}/run")
async def run_strategy(strategy_id: str, background: BackgroundTasks) -> dict:
    try:
        engine = get_backtest_engine()
        row = await engine.get(strategy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Strategy not found.")
        if row["status"] == "RUNNING":
            raise HTTPException(status_code=409, detail="Strategy is already running.")
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)
    background.add_task(engine.run, strategy_id)
    # Optimistic snapshot the UI adopts until the first poll. A PAUSED run resumes
    # (keep its partial progress/aggregates); any other state starts fresh, so clear
    # the prior result here too — otherwise a re-run of a COMPLETED strategy would
    # flash its old equity curve / net P&L at 100% under a RUNNING badge.
    optimistic = {**row, "status": "RUNNING"}
    if row["status"] != "PAUSED":
        optimistic.update(
            {
                "progress": 0.0, "processed_windows": 0,
                "final_capital": None, "net_pnl": None, "total_trades": 0,
                "win_rate": None, "rank": None, "report_md": None,
                "equity_curve": [], "per_window": [],
                "per_pair_pnl": {}, "exit_reasons": {},
            }
        )
    return optimistic


@router.post("/strategies/{strategy_id}/pause")
async def pause_strategy(strategy_id: str) -> dict:
    try:
        return await get_backtest_engine().request_pause(strategy_id)
    except StrategyNotFound:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    except Exception as exc:
        raise _guard_db(exc)


@router.post("/strategies/{strategy_id}/stop")
async def stop_strategy(strategy_id: str) -> dict:
    try:
        return await get_backtest_engine().request_stop(strategy_id)
    except StrategyNotFound:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    except Exception as exc:
        raise _guard_db(exc)


# Server-side blotter filters (issue: exit-reason vs P&L clarity). The reason a
# trade closed is a z-score/time signal rule, independent of its dollar result — so
# a TAKE_PROFIT can still be a net loss (small reversion eaten by fees + funding).
# ``losing_tp`` surfaces exactly that cohort (reason=TAKE_PROFIT AND net_pnl<0),
# which is the interesting set for tuning costs/half-life. Applied server-side so
# the total + pagination stay correct across the whole (paginated) result set.
_TRADE_OUTCOMES = {"losing_tp"}


@router.get("/strategies/{strategy_id}/trades")
async def list_trades(
    strategy_id: str,
    window: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    outcome: str | None = Query(default=None),
) -> dict:
    """Paginated per-trade blotter for a strategy (issue #162).

    ``window`` scopes to one walk-forward window (the UI drills in per window).
    ``outcome`` (currently only ``losing_tp``) filters to the losing-take-profit
    cohort — take-profit exits that still closed at a net dollar loss.
    Strategies run before this feature shipped simply have no trades → empty list.
    """
    if outcome is not None and outcome not in _TRADE_OUTCOMES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown outcome filter {outcome!r}; expected one of {sorted(_TRADE_OUTCOMES)}.",
        )
    try:
        engine = get_backtest_engine()
        row = await engine.get(strategy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Strategy not found.")
        result = await engine.list_trades(
            strategy_id, window_index=window, limit=limit, offset=offset, outcome=outcome
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)
    return {
        "id": strategy_id, "window": window,
        "limit": limit, "offset": offset, "outcome": outcome, **result,
    }


@router.get("/strategies/{strategy_id}/trades/{trade_id}/series")
async def trade_series(strategy_id: str, trade_id: str) -> dict:
    """Per-trade chart series (issue #166) — the four pair panels over the trade's
    test window, with the trade's own entry/exit marked.

    404 if the strategy/trade is unknown or the trade doesn't belong to the
    strategy; 422 if the window has too little cached history to chart.
    """
    from backtest.trade_series import build_backtest_trade_series

    try:
        engine = get_backtest_engine()
        strategy = await engine.get(strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found.")
        trade = await engine.get_trade(trade_id)
        if trade is None or trade["strategy_id"] != strategy_id:
            raise HTTPException(status_code=404, detail="Trade not found.")
        result = await build_backtest_trade_series(strategy, trade)
    except HTTPException:
        raise
    except Exception as exc:
        raise _guard_db(exc)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail="Not enough cached candle history to chart this trade's window.",
        )
    return result


@router.get("/strategies/{strategy_id}/report")
async def get_report(strategy_id: str) -> dict:
    try:
        row = await get_backtest_engine().get(strategy_id)
    except Exception as exc:
        raise _guard_db(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return {"id": strategy_id, "report_md": row.get("report_md"), "status": row["status"]}


# Baseline strategy set (PRD F8.1 — S1–S4 vary the Z-threshold / window). Offline
# (fake) mode uses short windows so the synthetic demo history yields several
# walk-forward steps; real mode uses the PRD's 90d-scan / 30d-trade windows.
def _default_strategies() -> list[dict]:
    fake = config.SCAN_DATA_SOURCE == "fake"
    scan_days, trade_days = (7, 3) if fake else (90, 30)
    specs = [
        ("S1 — Baseline", "Entry |Z|≥1.5, 21-bar window", 1.5, 21),
        ("S2 — Loose entry", "Entry |Z|≥1.0, 21-bar window", 1.0, 21),
        ("S3 — Tight entry", "Entry |Z|≥2.0, 21-bar window", 2.0, 21),
        ("S4 — Wide window", "Entry |Z|≥1.0, 30-bar window", 1.0, 30),
    ]
    return [
        {
            "exchange": config.active_exchange(),
            "data_source": config.SCAN_DATA_SOURCE,
            "name": name,
            "description": desc,
            "scan_window_days": scan_days,
            "trade_window_days": trade_days,
            "zscore_window": zwin,
            "entry_threshold": entry,
            "exit_threshold": config.EXIT_ZSCORE,
            "stop_threshold": config.STOP_LOSS_ZSCORE,
            "pvalue_max": config.PVALUE_MAX,
            "max_half_life_h": config.MAX_HALF_LIFE_H,
            "starting_capital": 10_000.0,
            "usd_per_trade": config.USD_PER_TRADE,
            "slippage_pct": 0.05,
            "taker_fee_pct": 0.05,
            "funding_freq_h": 1,
            "status": "PENDING",
        }
        for name, desc, entry, zwin in specs
    ]


@router.post("/seed-defaults", status_code=201)
async def seed_defaults() -> dict:
    """Create the S1–S4 baseline strategies (idempotent on name)."""
    _validate_exchange(config.DEFAULT_EXCHANGE)
    try:
        engine = get_backtest_engine()
        existing = {s["name"] for s in await engine.list()}
        created = []
        for spec in _default_strategies():
            if spec["name"] in existing:
                continue
            created.append(await engine.create(spec))
    except Exception as exc:
        raise _guard_db(exc)
    return {"created": created, "count": len(created)}
