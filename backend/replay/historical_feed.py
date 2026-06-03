"""
Historical feed for the fast-forward replay (PRD F7.1/F7.2) — the offline twin of
``simulation.feed``.

``simulation.feed.build_realtime_snapshots`` fetches *current* prices and computes
a rolling Z per pair. Here the prices are *historical*: each pair's two legs are
aligned on their shared timestamps once, then at every replay cursor we slice the
trailing window ending at that bar and compute the **same** ``statcore`` rolling Z
— so the replay drives the engine through identical signal logic, just over past
data. Pure: no DB, no IO, no config mutation.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from simulation.feed import PairTick
from statcore import compute_spread, latest_zscore


@dataclass(frozen=True)
class AlignedPair:
    """One pair's parameters plus its two legs aligned on shared timestamps."""

    base_market: str
    quote_market: str
    hedge_ratio: float
    intercept: float
    half_life: float
    timestamps: list[datetime]          # ascending, shared by both legs
    s1: np.ndarray                      # base closes
    s2: np.ndarray                      # quote closes
    _index: dict[datetime, int]         # timestamp → position

    def price_at(self, cursor: datetime) -> tuple[float, float] | None:
        """The (base, quote) close prices at ``cursor``, or None if there's no bar.

        Unlike :meth:`tick_at` this does **not** require a defined rolling Z — a
        zero-variance window yields no signal but the bar's prices still exist, and
        marking-to-market / force-closing need only prices. Returns None only when
        the pair genuinely has no bar at this cursor.
        """
        j = self._index.get(cursor)
        if j is None:
            return None
        return float(self.s1[j]), float(self.s2[j])

    def tick_at(self, cursor: datetime, *, window: int) -> PairTick | None:
        """Build a :class:`PairTick` for this pair at ``cursor`` (or None).

        Returns None when the pair has no bar at ``cursor``, has fewer than
        ``window`` bars of history up to it, or the trailing window has an
        undefined Z (zero variance) — mirroring the realtime feed's drop rules.
        """
        j = self._index.get(cursor)
        if j is None or (j + 1) < window:
            return None
        lo = j + 1 - window
        spread = compute_spread(
            self.s1[lo : j + 1], self.s2[lo : j + 1], self.hedge_ratio, self.intercept
        )
        z = latest_zscore(spread, window=window)
        if not np.isfinite(z):
            return None
        return PairTick(
            base_market=self.base_market,
            quote_market=self.quote_market,
            hedge_ratio=self.hedge_ratio,
            half_life=self.half_life,
            base_price=float(self.s1[j]),
            quote_price=float(self.s2[j]),
            z_score=float(z),
            spread_value=float(spread[-1]),
        )


def align_pairs(
    pairs: list[dict], candles_by_market: dict[str, list[dict]]
) -> list[AlignedPair]:
    """Align each pair's two legs on their shared timestamps.

    ``pairs`` are scan rows (base_market/quote_market/hedge_ratio/intercept/
    half_life); ``candles_by_market`` maps a market to ascending
    ``{"timestamp", "close"}`` dicts. Pairs whose legs share fewer than 2 bars are
    dropped (no usable history — nothing to replay).
    """
    aligned: list[AlignedPair] = []
    for p in pairs:
        base = candles_by_market.get(p["base_market"], [])
        quote = candles_by_market.get(p["quote_market"], [])
        base_by = {c["timestamp"]: float(c["close"]) for c in base}
        quote_by = {c["timestamp"]: float(c["close"]) for c in quote}
        shared = sorted(set(base_by) & set(quote_by))
        if len(shared) < 2:
            continue
        s1 = np.array([base_by[t] for t in shared], dtype=float)
        s2 = np.array([quote_by[t] for t in shared], dtype=float)
        aligned.append(
            AlignedPair(
                base_market=p["base_market"],
                quote_market=p["quote_market"],
                hedge_ratio=float(p["hedge_ratio"]),
                intercept=float(p.get("intercept") or 0.0),
                half_life=float(p.get("half_life") or 0.0),
                timestamps=shared,
                s1=s1,
                s2=s2,
                _index={t: i for i, t in enumerate(shared)},
            )
        )
    return aligned


def replay_timeline(
    aligned: list[AlignedPair], *, start: datetime, end: datetime
) -> list[datetime]:
    """The ordered set of cursor timestamps to tick: union of every pair's bars in
    [start, end]. Earlier (warm-up) history outside the window still feeds the
    rolling Z but is never itself a trading cursor.
    """
    stamps: set[datetime] = set()
    for ap in aligned:
        for t in ap.timestamps:
            if start <= t <= end:
                stamps.add(t)
    return sorted(stamps)


def snapshots_at(
    aligned: list[AlignedPair], cursor: datetime, *, window: int
) -> list[PairTick]:
    """All pairs with a usable signal at ``cursor``."""
    out: list[PairTick] = []
    for ap in aligned:
        tick = ap.tick_at(cursor, window=window)
        if tick is not None:
            out.append(tick)
    return out


class FundingTable:
    """Step-function funding lookup: the latest known rate at-or-before a cursor.

    Built from per-market ``{"timestamp", "funding_rate"}`` rows. ``rates_at``
    returns a market→rate dict for the markets it knows; markets with no data are
    simply absent (the engine treats a missing rate as zero). When *no* market has
    any funding data the table is empty, and the engine accrues no funding.
    """

    def __init__(self, funding_by_market: dict[str, list[dict]]) -> None:
        self._stamps: dict[str, list[datetime]] = {}
        self._rates: dict[str, list[float]] = {}
        for market, rows in funding_by_market.items():
            rows = sorted(rows, key=lambda r: r["timestamp"])
            self._stamps[market] = [r["timestamp"] for r in rows]
            self._rates[market] = [float(r["funding_rate"]) for r in rows]

    @property
    def empty(self) -> bool:
        return not any(self._rates.values())

    def rates_at(self, cursor: datetime, markets: set[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for market in markets:
            stamps = self._stamps.get(market)
            if not stamps:
                continue
            i = bisect.bisect_right(stamps, cursor) - 1
            if i >= 0:
                out[market] = self._rates[market][i]
        return out
