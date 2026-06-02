"""
Pure OHLCV validation & cleaning rules (Phase 2.5).

No DB, no I/O, no network — every function here operates on in-memory pandas
DataFrames, which makes the rules the highest-value unit-test surface of this
phase (see ``tests/test_ingest.py``).

A candle is **dropped** from the cache when it carries no usable price
information:

  * **non-positive price** — any of OHLC <= 0 is impossible/garbage;
  * **OHLC-inconsistent** — ``high < low``, or high/low not bracketing
    open/close;
  * **zero volume** — no trades occurred in the hour; dYdX forward-fills a flat
    bar in that case, which would pin the spread and distort cointegration;
  * **flat** — ``high == low`` (zero intra-bar range), the same forward-fill
    artefact even when a nominal volume is attached.

The rules are applied in that priority order to the *surviving* rows, so the
per-rule drop counts are disjoint and sum exactly to
``raw_rows = clean + unparseable + duplicates + nonpositive + inconsistent +
zero_volume + flat`` — a property the tests assert.

Gaps (missing hourly bars) are **detected and reported, never silently filled**:
the downstream replay/backtest decides how to handle them. Coverage enforcement
(dropping under-covered markets) is a pipeline concern, not a cleaning one.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
_OHLC = ["open", "high", "low", "close"]


@dataclass(frozen=True)
class CleaningStats:
    """Disjoint, additive accounting of one market's cleaning pass."""

    raw_rows: int
    dropped_unparseable: int
    duplicates_dropped: int
    dropped_nonpositive: int
    dropped_inconsistent: int
    dropped_zero_volume: int
    dropped_flat: int
    clean_rows: int
    gap_count: int          # total missing hourly bars within [first, last]
    largest_gap_hours: int  # longest single run of consecutive missing bars

    @property
    def dropped_total(self) -> int:
        return (
            self.dropped_unparseable
            + self.duplicates_dropped
            + self.dropped_nonpositive
            + self.dropped_inconsistent
            + self.dropped_zero_volume
            + self.dropped_flat
        )


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Parse timestamp → UTC datetime and OHLCV → float, non-destructively."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in (*_OHLC, "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def detect_gaps(timestamps: pd.Series, *, step_hours: int = 1) -> tuple[int, int]:
    """
    Count missing bars on the expected fixed-cadence grid spanning the data.

    Returns ``(gap_count, largest_gap_hours)`` where ``gap_count`` is the total
    number of absent bars between the first and last timestamp and
    ``largest_gap_hours`` is the longest single run of consecutive absences.
    Requires at least two timestamps; otherwise returns ``(0, 0)``.
    """
    ts = pd.DatetimeIndex(pd.Series(timestamps).dropna()).sort_values()
    if len(ts) < 2:
        return (0, 0)
    step = pd.Timedelta(hours=step_hours)
    deltas = ts.to_series().diff().dropna()
    total = 0
    largest = 0
    for d in deltas:
        missing = int(round(d / step)) - 1
        if missing > 0:
            total += missing
            largest = max(largest, missing)
    return total, largest


def clean_ohlcv(
    df: pd.DataFrame,
    *,
    drop_flat: bool = True,
    drop_zero_volume: bool = True,
    step_hours: int = 1,
) -> tuple[pd.DataFrame, CleaningStats]:
    """
    Validate and clean a raw OHLCV frame.

    Returns ``(clean_df, stats)``. ``clean_df`` has the canonical column order,
    is sorted by timestamp, de-duplicated, and contains only usable candles.
    Missing required columns raise ``ValueError`` (a structural error, not dirty
    data).
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")

    raw_rows = len(df)
    df = _coerce(df)

    # 1. Unparseable: any required field failed to parse.
    bad = df[list(REQUIRED_COLUMNS)].isna().any(axis=1)
    dropped_unparseable = int(bad.sum())
    df = df[~bad]

    # 2. Duplicate timestamps (keep the last — values are identical in practice).
    df = df.sort_values("timestamp", kind="stable")
    dup = df["timestamp"].duplicated(keep="last")
    duplicates_dropped = int(dup.sum())
    df = df[~dup]

    # 3. Non-positive prices.
    nonpos = (df[_OHLC] <= 0).any(axis=1)
    dropped_nonpositive = int(nonpos.sum())
    df = df[~nonpos]

    # 4. OHLC inconsistency.
    oc_max = df[["open", "close"]].max(axis=1)
    oc_min = df[["open", "close"]].min(axis=1)
    inconsistent = (df["high"] < df["low"]) | (df["high"] < oc_max) | (df["low"] > oc_min)
    dropped_inconsistent = int(inconsistent.sum())
    df = df[~inconsistent]

    # 5. Zero (or negative) volume.
    dropped_zero_volume = 0
    if drop_zero_volume:
        zero_vol = df["volume"] <= 0
        dropped_zero_volume = int(zero_vol.sum())
        df = df[~zero_vol]

    # 6. Flat bars (zero intra-bar range), incl. forward-fills with nominal volume.
    dropped_flat = 0
    if drop_flat:
        flat = df["high"] == df["low"]
        dropped_flat = int(flat.sum())
        df = df[~flat]

    df = df[list(REQUIRED_COLUMNS)].reset_index(drop=True)
    gap_count, largest_gap = detect_gaps(df["timestamp"], step_hours=step_hours)

    stats = CleaningStats(
        raw_rows=raw_rows,
        dropped_unparseable=dropped_unparseable,
        duplicates_dropped=duplicates_dropped,
        dropped_nonpositive=dropped_nonpositive,
        dropped_inconsistent=dropped_inconsistent,
        dropped_zero_volume=dropped_zero_volume,
        dropped_flat=dropped_flat,
        clean_rows=len(df),
        gap_count=gap_count,
        largest_gap_hours=largest_gap,
    )
    return df, stats


def clean_funding(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """
    Light cleaning for a funding-rate frame: coerce types, drop unparseable
    rows, sort, and de-duplicate on timestamp. No OHLC-style rules apply (a
    funding row is a single rate per timestamp).

    Returns ``(clean_df, raw_rows, duplicates_dropped)``.
    """
    cols = ("timestamp", "funding_rate")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Funding frame missing columns: {missing}")

    raw_rows = len(df)
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
    df = df[~df[list(cols)].isna().any(axis=1)]
    df = df.sort_values("timestamp", kind="stable")
    dup = df["timestamp"].duplicated(keep="last")
    duplicates_dropped = int(dup.sum())
    df = df[~dup][list(cols)].reset_index(drop=True)
    return df, raw_rows, duplicates_dropped
