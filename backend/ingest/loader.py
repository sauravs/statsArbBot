"""
Filesystem loader for the copied dYdX historical CSVs (Phase 2.5).

Reads the ``{MARKET}_ohlcv_1h.csv`` / ``{MARKET}_funding.csv`` files that were
copied from the reference prototype into the gitignored ``data/dydx`` and
``data/dydx_extended`` directories (see ADR-0006). Pure filesystem + pandas; no
DB, no network.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OHLCV_SUFFIX = "_ohlcv_1h.csv"
FUNDING_SUFFIX = "_funding.csv"


def market_from_ohlcv_path(path: Path) -> str:
    return path.name[: -len(OHLCV_SUFFIX)]


def funding_path_for(ohlcv_path: Path) -> Path:
    """The sibling funding CSV for an OHLCV file (may not exist)."""
    market = market_from_ohlcv_path(ohlcv_path)
    return ohlcv_path.parent / f"{market}{FUNDING_SUFFIX}"


def iter_ohlcv_paths(data_dirs: list[str] | list[Path]) -> list[Path]:
    """
    Return all OHLCV CSV paths across the given directories, sorted by market.

    Directories that don't exist are skipped with a warning. If the same market
    appears in more than one directory, the first occurrence (in ``data_dirs``
    order) wins and the later one is skipped — the two reference dirs are
    disjoint in practice (ADR-0006), this is just a guard.
    """
    seen: set[str] = set()
    paths: list[Path] = []
    for d in data_dirs:
        directory = Path(d)
        if not directory.is_dir():
            logger.warning("Ingest data dir not found, skipping: %s", directory)
            continue
        for p in sorted(directory.glob(f"*{OHLCV_SUFFIX}")):
            market = market_from_ohlcv_path(p)
            if market in seen:
                logger.warning("Duplicate market %s in %s — keeping earlier dir", market, directory)
                continue
            seen.add(market)
            paths.append(p)
    return paths


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    """Load a raw OHLCV CSV (columns: timestamp, open, high, low, close, volume)."""
    return pd.read_csv(path)


def load_funding_csv(path: Path) -> pd.DataFrame:
    """Load a raw funding CSV (columns: timestamp, funding_rate)."""
    return pd.read_csv(path)
