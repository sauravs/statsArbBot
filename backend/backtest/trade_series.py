"""
Per-trade chart series for a walk-forward backtest trade (issue #166).

The blotter (issue #162) shows where/when each trade entered & exited; this builds
the data for the trade's *chart* — the same four panels the Manual Trading pair
view draws (normalized price, dual-axis raw price, spread with ±σ bands, rolling
z-score), scoped to the trade's **test window** with the trade's own entry/exit
marked.

Faithfulness: the spread/z panels are reproduced from the pair's cointegration
params (β/α) as the backtest actually traded them — persisted on the trade row
(issue #166). Trades recorded before that persistence exist without β/α; for them
only the two price panels are trustworthy (``faithful=False``), so the UI hides the
spread/z panels rather than show a β=1 placeholder.

Pure apart from the candle fetch (a ``CandleSource``); no DB, no config mutation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from marketdata.pair_series import pair_series_from_closes
from replay.candle_source import make_candle_source


def _aware(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _window_for(strategy: dict, window_index: int) -> dict | None:
    """The per_window summary row this trade belongs to (matched by index)."""
    for w in strategy.get("per_window") or []:
        if w.get("index") == window_index:
            return w
    return None


def _align(base_candles, quote_candles):
    """Inner-join two candle lists on timestamp → (shared_dts, s1, s2) ascending."""
    b = {_aware(c["timestamp"]): float(c["close"]) for c in base_candles}
    q = {_aware(c["timestamp"]): float(c["close"]) for c in quote_candles}
    shared = sorted(set(b) & set(q))
    if len(shared) < 2:
        return None
    return shared, [b[t] for t in shared], [q[t] for t in shared]


def _overlay(time_val, z, base_px, quote_px, beta, alpha) -> dict:
    """The trade's entry (or exit) marker/price-line overlay for the chart."""
    spread = None
    if beta is not None and base_px is not None and quote_px is not None:
        spread = float(base_px) - float(beta) * float(quote_px) - float(alpha or 0.0)
    return {
        "time": int(_aware(time_val).timestamp()),
        "z": z,
        "priceBase": base_px,
        "priceQuote": quote_px,
        "spread": spread,
    }


async def build_backtest_trade_series(
    strategy: dict, trade: dict, *, source=None
) -> dict | None:
    """Build the per-trade chart payload, or ``None`` if the window can't be charted.

    Returns ``None`` when the trade's window is unknown or the two legs share too
    little overlapping cached history to plot.
    """
    base = trade["base_market"]
    quote = trade["quote_market"]
    zwindow = int(strategy["zscore_window"])

    win = _window_for(strategy, int(trade["window_index"]))
    if win is None:
        return None
    trade_start = _aware(win["trade_start"])
    trade_end = _aware(win["trade_end"])
    # Pad the load start by the z-window so the rolling z is warm at trade_start.
    load_start = trade_start - timedelta(hours=zwindow + 2)

    source = source or make_candle_source(exchange=strategy["exchange"])
    base_candles = await source.get_candles(base, start=load_start, end=trade_end)
    quote_candles = await source.get_candles(quote, start=load_start, end=trade_end)
    aligned = _align(base_candles, quote_candles)
    if aligned is None:
        return None
    shared, s1, s2 = aligned
    times = [int(dt.timestamp()) for dt in shared]

    beta = trade.get("hedge_ratio")
    alpha = trade.get("intercept") or 0.0
    faithful = beta is not None
    series = pair_series_from_closes(
        base,
        quote,
        times=times,
        s1=s1,
        s2=s2,
        window_start=shared[0].isoformat(),
        window_end=shared[-1].isoformat(),
        # Legacy trades (pre-#166) have no β/α — pass a β=1 placeholder so the price
        # panels still compute; the UI hides spread/z when faithful is False.
        hedge_ratio=float(beta) if faithful else 1.0,
        intercept=float(alpha),
        half_life=trade.get("half_life"),
        window=zwindow,
        markers=[],  # the trade's own entry/exit overlay replaces model markers
    )
    series_dict = series.to_dict()
    if not faithful:
        # No β/α for this (pre-#166) trade → the spread/z would be a β=1 placeholder,
        # which is wrong, not just approximate. Blank those panels so the UI shows
        # only the two faithful price panels + a "re-run for full charts" note.
        series_dict["spread"] = {"mean": 0.0, "std": 0.0, "series": []}
        series_dict["zscore"] = {"series": [], "markers": []}

    return {
        "trade_id": trade["id"],
        "strategy_id": trade["strategy_id"],
        "base_market": base,
        "quote_market": quote,
        "window_index": trade["window_index"],
        "direction": trade["direction"],
        "exit_reason": trade["exit_reason"],
        # P&L decomposition so the chart can explain WHY a take-profit still lost
        # money: net = gross − fees + funding (funding signed). A small spread
        # reversion (gross) eaten by round-trip taker fees + funding over the hold
        # is exactly how a TAKE_PROFIT row ends up red.
        "gross_pnl": trade["gross_pnl"],
        "fee_cost": trade["fee_cost"],
        "funding_pnl": trade["funding_pnl"],
        "net_pnl": trade["net_pnl"],
        # Whether the spread/z panels reproduce what the backtest traded (β/α known).
        "faithful": faithful,
        "series": series_dict,
        "entry": _overlay(
            trade["entry_time"], trade["entry_z"],
            trade["entry_base_px"], trade["entry_quote_px"], beta, alpha,
        ),
        "exit": _overlay(
            trade["exit_time"], trade["exit_z"],
            trade["exit_base_px"], trade["exit_quote_px"], beta, alpha,
        ),
    }
