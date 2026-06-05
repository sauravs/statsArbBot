"""Shared test fixtures and synthetic market-data helpers for Phase 2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

# Anchor for deterministic synthetic candle timestamps.
_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_cointegrated_series(n: int = 400, *, seed: int = 7) -> tuple[list[float], list[float]]:
    """
    Build a strongly cointegrated pair: S2 is a random walk; S1 = 2·S2 + α + ε
    where ε is a fast mean-reverting AR(1) (phi=0.5 → ~1-period half-life). The
    spread S1 − 2·S2 is stationary, so Engle-Granger should accept it with a small
    p-value and a half-life well inside the 72h cap.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1, n)
    s2 = 100 + np.cumsum(steps)  # random walk
    eps = np.zeros(n)
    for t in range(1, n):
        eps[t] = 0.5 * eps[t - 1] + rng.normal(0, 0.5)
    s1 = 2.0 * s2 + 5.0 + eps
    return s1.tolist(), s2.tolist()


def make_independent_walk(n: int = 400, *, seed: int = 99) -> list[float]:
    """An independent random walk — not cointegrated with the pair above."""
    rng = np.random.default_rng(seed)
    return (50 + np.cumsum(rng.normal(0, 1, n))).tolist()


def make_flat_series(n: int = 400, *, value: float = 100.0) -> list[float]:
    """A constant series — degenerate input that makes coint()/OLS misbehave."""
    return [value] * n


def closes_to_candles(closes: list[float]) -> list[dict]:
    """Convert a close list into the {datetime, close} shape the client returns."""
    return [
        {"datetime": _iso(_ANCHOR + timedelta(hours=i)), "close": float(c)}
        for i, c in enumerate(closes)
    ]


class FakeDydxClient:
    """In-memory PriceSource: serves preset close series, no network."""

    def __init__(self, series: dict[str, list[float]]) -> None:
        self._series = series
        self.closed = False

    async def get_markets(self) -> dict[str, dict]:
        return {m: {"status": "ACTIVE"} for m in self._series}

    async def get_historical_closes(
        self, market: str, *, num_pages=None, now=None, concurrent: bool = False
    ) -> list[dict]:
        self.last_num_pages = num_pages
        self.last_concurrent = concurrent
        return closes_to_candles(self._series.get(market, []))

    async def aclose(self) -> None:
        self.closed = True


class FakeScanRepository:
    """In-memory stand-in for PrismaScanRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], list[dict]] = {}

    async def replace_scan_results(self, rows, *, exchange, mode) -> int:
        # Serialise datetimes the way the Prisma version's reader would emit them.
        serialised = []
        for r in rows:
            row = dict(r)
            for k in ("scanned_at", "window_start", "window_end"):
                v = row.get(k)
                if isinstance(v, datetime):
                    row[k] = v.isoformat()
            serialised.append(row)
        self.store[(exchange, mode)] = serialised
        return len(serialised)

    async def get_latest_pairs(self, *, exchange, mode) -> list[dict]:
        rows = self.store.get((exchange, mode), [])
        # Mirror PrismaScanRepository: zero_crossings desc, p_value asc tie-break.
        return sorted(rows, key=lambda r: (-r["zero_crossings"], r["p_value"]))

    async def get_pair(self, *, exchange, mode, base_market, quote_market):
        pairs = await self.get_latest_pairs(exchange=exchange, mode=mode)
        return next(
            (
                p
                for p in pairs
                if p["base_market"] == base_market
                and p["quote_market"] == quote_market
            ),
            None,
        )


class FakeOhlcvCacheRepository:
    """In-memory stand-in for PrismaOhlcvCacheRepository (no DB / generated client).

    Replicates the replace-on-write semantics so the ingest pipeline can be
    driven end-to-end in unit tests without Postgres.
    """

    def __init__(self) -> None:
        self.candles: dict[tuple[str, str, str], list[dict]] = {}
        self.funding: dict[tuple[str, str], list[dict]] = {}

    async def replace_candles(self, market, rows, *, exchange, resolution) -> int:
        self.candles[(exchange, market, resolution)] = list(rows)
        return len(rows)

    async def replace_funding(self, market, rows, *, exchange) -> int:
        self.funding[(exchange, market)] = list(rows)
        return len(rows)

    async def get_candles(self, market, *, exchange, resolution, start=None, end=None):
        rows = self.candles.get((exchange, market, resolution), [])
        out = [{"timestamp": r["timestamp"], "close": r["close"]} for r in rows]
        if start is not None:
            out = [r for r in out if r["timestamp"] >= start]
        if end is not None:
            out = [r for r in out if r["timestamp"] <= end]
        return sorted(out, key=lambda r: r["timestamp"])

    async def get_funding(self, market, *, exchange, start=None, end=None):
        rows = self.funding.get((exchange, market), [])
        out = [{"timestamp": r["timestamp"], "funding_rate": r["funding_rate"]} for r in rows]
        if start is not None:
            out = [r for r in out if r["timestamp"] >= start]
        if end is not None:
            out = [r for r in out if r["timestamp"] <= end]
        return sorted(out, key=lambda r: r["timestamp"])

    async def get_markets(self, *, exchange, resolution) -> list[str]:
        return sorted(
            {m for (ex, m, res) in self.candles if ex == exchange and res == resolution}
        )


class FakeTradeClient:
    """In-memory stand-in for a dYdX trade client (Phase 5a).

    Simulates fills by tracking positions, lets tests force submission/close
    failures and fill timeouts, and serves controllable collateral/equity. Mirrors
    the ``trading.broker.TradeClient`` protocol so the engine drives it unchanged.
    """

    def __init__(
        self,
        *,
        prices: dict[str, float] | None = None,
        free_collateral: float = 10_000.0,
        equity: float = 10_000.0,
        fail_open_markets: set[str] | None = None,
        fail_close_markets: set[str] | None = None,
        no_fill_markets: set[str] | None = None,
    ) -> None:
        from trading.broker import OrderResult, Position

        self._OrderResult = OrderResult
        self._Position = Position
        self.prices = prices or {}
        self.free_collateral = free_collateral
        self.equity = equity
        self.fail_open_markets = set(fail_open_markets or [])
        self.fail_close_markets = set(fail_close_markets or [])
        self.no_fill_markets = set(no_fill_markets or [])
        self.positions: dict[str, object] = {}
        self.orders: list[dict] = []
        self.cancelled = False
        self.closed = False

    async def place_market_order(self, *, market, side, size, reduce_only=False):
        if reduce_only and market in self.fail_close_markets:
            return None
        if not reduce_only and market in self.fail_open_markets:
            return None
        price = self.prices.get(market, 100.0)
        self.orders.append(
            {"market": market, "side": side, "size": size, "reduce_only": reduce_only, "price": price}
        )
        if reduce_only:
            self.positions.pop(market, None)
        elif market not in self.no_fill_markets:
            self.positions[market] = self._Position(
                market=market,
                side="LONG" if side == "BUY" else "SHORT",
                size=size,
                entry_price=price,
            )
        return self._OrderResult(
            market=market, side=side, size=size, price=price, client_id=1, reduce_only=reduce_only
        )

    async def is_open_position(self, market):
        return market in self.positions

    async def get_open_positions(self):
        return dict(self.positions)

    async def get_free_collateral(self):
        return self.free_collateral

    async def get_account_equity(self):
        return self.equity

    async def cancel_all_orders(self):
        self.cancelled = True

    async def aclose(self):
        self.closed = True


class FakeLiveRepository:
    """In-memory stand-in for PrismaLiveRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    # sessions
    async def get_active_session(self, *, exchange, mode):
        actives = [
            s
            for s in self.sessions.values()
            if s["exchange"] == exchange and s["mode"] == mode and s["active"]
        ]
        return dict(actives[-1]) if actives else None

    async def start_session(self, *, exchange, mode):
        existing = await self.get_active_session(exchange=exchange, mode=mode)
        if existing is not None:
            return existing
        self._seq += 1
        sid = f"ls_{self._seq}"
        self.sessions[sid] = {
            "id": sid,
            "exchange": exchange,
            "mode": mode,
            "active": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stopped_at": None,
        }
        return dict(self.sessions[sid])

    async def stop_session(self, *, exchange, mode):
        n = 0
        for s in self.sessions.values():
            if s["exchange"] == exchange and s["mode"] == mode and s["active"]:
                s["active"] = False
                s["stopped_at"] = datetime.now(timezone.utc).isoformat()
                n += 1
        return n

    # trades
    async def create_trade(self, data):
        self._seq += 1
        tid = f"lt_{self._seq}"
        row = dict(data)
        row["opened_at"] = self._iso(row.get("opened_at"))
        row.setdefault("status", "PENDING")
        row.update(
            id=tid,
            exit_z_score=row.get("exit_z_score"),
            exit_price_leg1=row.get("exit_price_leg1"),
            exit_price_leg2=row.get("exit_price_leg2"),
            exit_reason=row.get("exit_reason"),
            pnl=row.get("pnl"),
            closed_at=row.get("closed_at"),
            error=row.get("error"),
        )
        self.trades[tid] = row
        return dict(row)

    async def list_trades(self, *, exchange, mode, status=None):
        rows = [
            r
            for r in self.trades.values()
            if r["exchange"] == exchange and r["mode"] == mode
            and (status is None or r["status"] == status)
        ]
        return [dict(r) for r in sorted(rows, key=lambda r: r["opened_at"], reverse=True)]

    async def get_open_trades(self, *, exchange, mode):
        return await self.list_trades(exchange=exchange, mode=mode, status="OPEN")

    async def close_trade(
        self, trade_id, *, exit_price_leg1, exit_price_leg2, exit_z_score, exit_reason, pnl, closed_at
    ):
        row = self.trades.get(trade_id)
        if row is None:
            return None
        row.update(
            status="CLOSED",
            exit_price_leg1=exit_price_leg1,
            exit_price_leg2=exit_price_leg2,
            exit_z_score=exit_z_score,
            exit_reason=exit_reason,
            pnl=pnl,
            closed_at=self._iso(closed_at),
        )
        return dict(row)

    async def mark_error(self, trade_id, *, error):
        row = self.trades.get(trade_id)
        if row is None:
            return None
        row.update(status="ERROR", error=error)
        return dict(row)


class FakeSimRepository:
    """In-memory stand-in for PrismaSimRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.positions: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    def _ser_dt(self, row: dict, keys) -> dict:
        out = dict(row)
        for k in keys:
            out[k] = self._iso(out.get(k))
        return out

    # sessions
    _SESSION_DEFAULTS = {
        "label": None,
        "status": "RUNNING",
        "interval_seconds": 60,
        "zscore_window": 21,
        "entry_threshold": 1.5,
        "exit_threshold": 0.5,
        "stop_threshold": 4.0,
        "usd_per_trade": 100.0,
        "max_active_pairs": None,
        "slippage_pct": 0.05,
        "taker_fee_pct": 0.05,
        "funding_freq_h": 1,
        "tick_count": 0,
        "last_tick_at": None,
        "stopped_at": None,
        "mode": "simulation",
        "exchange": "dydx",
    }

    async def create_session(self, params: dict) -> dict:
        self._seq += 1
        sid = f"ss_{self._seq}"
        row = {**self._SESSION_DEFAULTS, **params}
        row.setdefault("current_capital", row.get("starting_capital"))
        row["id"] = sid
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        self.sessions[sid] = self._ser_dt(row, ("last_tick_at", "stopped_at"))
        return dict(self.sessions[sid])

    async def get_session(self, session_id: str):
        row = self.sessions.get(session_id)
        return dict(row) if row is not None else None

    async def list_sessions(self) -> list[dict]:
        rows = sorted(
            self.sessions.values(), key=lambda r: r["created_at"], reverse=True
        )
        out = []
        for r in rows:
            d = dict(r)
            d["realised_pnl"] = sum(
                t["net_pnl"] for t in self.trades.values() if t["session_id"] == r["id"]
            )
            out.append(d)
        return out

    async def list_running_sessions(self) -> list[dict]:
        return [dict(r) for r in self.sessions.values() if r["status"] == "RUNNING"]

    async def update_session(self, session_id: str, data: dict):
        row = self.sessions.get(session_id)
        if row is None:
            return None
        row.update(self._ser_dt(data, ("last_tick_at", "stopped_at")))
        return dict(row)

    # positions
    async def create_position(self, data: dict) -> dict:
        self._seq += 1
        pid = f"sp_{self._seq}"
        row = self._ser_dt(data, ("entry_time",))
        row["id"] = pid
        row.setdefault("status", "OPEN")
        row.setdefault("funding_pnl", 0.0)
        self.positions[pid] = row
        return dict(row)

    async def get_open_positions(self, session_id: str) -> list[dict]:
        rows = [
            r
            for r in self.positions.values()
            if r["session_id"] == session_id and r["status"] == "OPEN"
        ]
        return [dict(r) for r in sorted(rows, key=lambda r: r["entry_time"])]

    async def update_position(self, position_id: str, data: dict):
        row = self.positions.get(position_id)
        if row is None:
            return None
        row.update(data)
        return dict(row)

    async def close_position(self, position_id: str):
        return await self.update_position(position_id, {"status": "CLOSED"})

    # trades
    async def create_trade(self, data: dict) -> dict:
        self._seq += 1
        tid = f"st_{self._seq}"
        row = self._ser_dt(data, ("entry_time", "exit_time"))
        row["id"] = tid
        self.trades[tid] = row
        return dict(row)

    async def list_trades(self, session_id: str) -> list[dict]:
        rows = [r for r in self.trades.values() if r["session_id"] == session_id]
        return [dict(r) for r in sorted(rows, key=lambda r: r["exit_time"], reverse=True)]


class FakeFFRepository:
    """In-memory stand-in for PrismaFFRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _ser(data: dict) -> dict:
        row = dict(data)
        for k in ("start_time", "end_time", "created_at", "completed_at"):
            v = row.get(k)
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        return row

    _DEFAULTS = {
        "label": None,
        "status": "RUNNING",
        "speed": 3600,
        "zscore_window": 21,
        "entry_threshold": 1.5,
        "exit_threshold": 0.5,
        "stop_threshold": 4.0,
        "usd_per_trade": 100.0,
        "max_active_pairs": None,
        "slippage_pct": 0.05,
        "taker_fee_pct": 0.05,
        "funding_freq_h": 1,
        "pairs_count": 0,
        "total_ticks": 0,
        "processed_ticks": 0,
        "progress": 0.0,
        "final_capital": None,
        "realised_pnl": None,
        "total_trades": 0,
        "equity_curve": None,
        "per_pair_pnl": None,
        "exit_reasons": None,
        "error": None,
        "completed_at": None,
        "exchange": "dydx",
    }

    async def create(self, params: dict) -> dict:
        self._seq += 1
        fid = f"ff_{self._seq}"
        row = {**self._DEFAULTS, **self._ser(params)}
        row["id"] = fid
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        self.store[fid] = row
        return dict(row)

    async def get(self, ff_id: str):
        row = self.store.get(ff_id)
        return dict(row) if row is not None else None

    async def list(self) -> list[dict]:
        rows = sorted(self.store.values(), key=lambda r: r["created_at"], reverse=True)
        return [dict(r) for r in rows]

    async def update(self, ff_id: str, data: dict):
        row = self.store.get(ff_id)
        if row is None:
            return None
        row.update(self._ser(data))
        return dict(row)


class FakeStrategyRepository:
    """In-memory stand-in for PrismaStrategyRepository (no DB / generated client)."""

    _DEFAULTS = {
        "description": None,
        "status": "PENDING",
        "scan_window_days": 90,
        "trade_window_days": 30,
        "zscore_window": 21,
        "entry_threshold": 1.5,
        "exit_threshold": 0.5,
        "stop_threshold": 4.0,
        "pvalue_max": 0.05,
        "max_half_life_h": 72.0,
        "start_time": None,
        "end_time": None,
        "starting_capital": 10_000.0,
        "usd_per_trade": 100.0,
        "max_active_pairs": None,
        "slippage_pct": 0.05,
        "taker_fee_pct": 0.05,
        "funding_freq_h": 1,
        "total_windows": 0,
        "processed_windows": 0,
        "progress": 0.0,
        "current_capital": None,
        "final_capital": None,
        "net_pnl": None,
        "total_trades": 0,
        "win_rate": None,
        "rank": None,
        "equity_curve": None,
        "per_window": None,
        "per_pair_pnl": None,
        "exit_reasons": None,
        "report_md": None,
        "error": None,
        "completed_at": None,
        "exchange": "dydx",
    }

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _ser(data: dict) -> dict:
        row = dict(data)
        for k in ("start_time", "end_time", "created_at", "updated_at", "completed_at"):
            v = row.get(k)
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        return row

    async def create(self, params: dict) -> dict:
        self._seq += 1
        sid = f"strat_{self._seq}"
        row = {**self._DEFAULTS, **self._ser(params)}
        now = datetime.now(timezone.utc).isoformat()
        row["id"] = sid
        row["created_at"] = now
        row["updated_at"] = now
        self.store[sid] = row
        return dict(row)

    async def get(self, strategy_id: str):
        row = self.store.get(strategy_id)
        return dict(row) if row is not None else None

    async def list(self) -> list[dict]:
        rows = list(self.store.values())
        ranked = sorted((r for r in rows if r.get("rank")), key=lambda r: r["rank"])
        unranked = sorted(
            (r for r in rows if not r.get("rank")),
            key=lambda r: r.get("created_at") or "",
            reverse=True,
        )
        return [dict(r) for r in (ranked + unranked)]

    async def update(self, strategy_id: str, data: dict):
        row = self.store.get(strategy_id)
        if row is None:
            return None
        row.update(self._ser(data))
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(row)

    async def delete(self, strategy_id: str) -> bool:
        return self.store.pop(strategy_id, None) is not None

    async def recompute_ranks(self) -> None:
        ranked = sorted(
            (r for r in self.store.values() if r.get("net_pnl") is not None),
            key=lambda r: (-r["net_pnl"], r.get("created_at") or ""),
        )
        ranked_ids = {r["id"] for r in ranked}
        for i, r in enumerate(ranked, start=1):
            r["rank"] = i
        for r in self.store.values():
            if r["id"] not in ranked_ids:
                r["rank"] = None


class FakeManualTradeRepository:
    """In-memory stand-in for PrismaManualTradeRepository (no DB / generated client)."""

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self._seq = 0

    @staticmethod
    def _ser(data: dict) -> dict:
        row = dict(data)
        for k in ("recorded_at", "closed_at"):
            v = row.get(k)
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        return row

    async def create(self, data: dict) -> dict:
        self._seq += 1
        trade_id = f"mt_{self._seq}"
        row = self._ser(data)
        row.setdefault("status", "OPEN")
        row.update(
            id=trade_id,
            closed_at=row.get("closed_at"),
            exit_price_leg1=row.get("exit_price_leg1"),
            exit_price_leg2=row.get("exit_price_leg2"),
            pnl=row.get("pnl"),
        )
        self.store[trade_id] = row
        return dict(row)

    async def list(self, *, exchange, mode, data_source=None) -> list[dict]:
        rows = [
            r
            for r in self.store.values()
            if r["exchange"] == exchange
            and r["mode"] == mode
            and (data_source is None or r.get("data_source") == data_source)
        ]
        # Mirror PrismaManualTradeRepository: newest first.
        return [dict(r) for r in sorted(rows, key=lambda r: r["recorded_at"], reverse=True)]

    async def get(self, trade_id) -> dict | None:
        row = self.store.get(trade_id)
        return dict(row) if row is not None else None

    async def close(
        self, trade_id, *, exit_price_leg1, exit_price_leg2, pnl, closed_at
    ) -> dict | None:
        row = self.store.get(trade_id)
        if row is None:
            return None
        row.update(
            status="CLOSED",
            exit_price_leg1=exit_price_leg1,
            exit_price_leg2=exit_price_leg2,
            pnl=pnl,
            closed_at=closed_at.isoformat() if isinstance(closed_at, datetime) else closed_at,
        )
        return dict(row)

    async def delete(self, trade_id) -> bool:
        return self.store.pop(trade_id, None) is not None
