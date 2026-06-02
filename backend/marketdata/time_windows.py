"""
Paginated ISO time windows for the dYdX candles REST API.

The indexer caps each candle request at ``candles_per_page`` bars, so historical
fetches walk backwards in fixed-width windows. Each window spans
``candles_per_page * hours_per_candle`` hours; ``num_pages`` windows are returned
oldest-first so concatenating their candles yields chronological data.

``now`` is injectable so tests are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Hours represented by each candle resolution dYdX supports.
_RESOLUTION_HOURS: dict[str, float] = {
    "1MIN": 1 / 60,
    "5MINS": 5 / 60,
    "15MINS": 15 / 60,
    "30MINS": 30 / 60,
    "1HOUR": 1.0,
    "4HOURS": 4.0,
    "1DAY": 24.0,
}

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def iso_time_windows(
    num_pages: int,
    *,
    resolution: str = "1HOUR",
    candles_per_page: int = 100,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Build ``num_pages`` time windows going back from ``now``.

    Returns a list of ``{"from_iso", "to_iso"}`` dicts ordered oldest-first.
    """
    if num_pages <= 0:
        return []

    hours_per_candle = _RESOLUTION_HOURS.get(resolution, 1.0)
    window_hours = candles_per_page * hours_per_candle
    anchor = now or datetime.now(timezone.utc)

    windows: list[dict[str, str]] = []
    for i in range(num_pages):
        to_time = anchor - timedelta(hours=i * window_hours)
        from_time = to_time - timedelta(hours=window_hours)
        windows.append(
            {
                "from_iso": from_time.strftime(_ISO_FMT),
                "to_iso": to_time.strftime(_ISO_FMT),
            }
        )

    windows.reverse()  # oldest window first
    return windows
