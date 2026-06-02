"""
Historical-data ingest & validation (Phase 2.5).

Seeds the ``OhlcvCache`` / ``FundingRateCache`` tables from the copied dYdX CSVs
(``data/dydx`` + ``data/dydx_extended``) after a validation/cleaning pass that
drops dirty candles and excludes under-covered markets (see ADR-0006). Feeds the
fast-forward simulation (Phase 7) and walk-forward backtest (Phase 8).

Pure rules live in :mod:`ingest.cleaning`; orchestration in :mod:`ingest.pipeline`.
"""

from .cleaning import CleaningStats, clean_funding, clean_ohlcv, detect_gaps
from .cache_repository import (
    PrismaOhlcvCacheRepository,
    get_ohlcv_cache_repository,
)
from .pipeline import run_ingest
from .report import FundingReport, IngestReport, MarketReport

__all__ = [
    "CleaningStats",
    "clean_ohlcv",
    "clean_funding",
    "detect_gaps",
    "run_ingest",
    "IngestReport",
    "MarketReport",
    "FundingReport",
    "PrismaOhlcvCacheRepository",
    "get_ohlcv_cache_repository",
]
