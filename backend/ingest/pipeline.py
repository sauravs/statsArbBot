"""
Historical-data ingest pipeline (Phase 2.5).

Orchestrates: discover CSVs (loader) → clean OHLCV (cleaning) → enforce coverage
→ seed the cache (cache_repository) → accumulate a validation report (report).
Funding rows are ingested alongside (light dedup only). The same flow runs in
``dry_run`` mode (build the report, write nothing) for inspection and tests.

Per ADR-0006, the cache holds only CLEAN candles and only markets that meet the
coverage threshold; everything dropped or excluded is accounted for in the
returned :class:`IngestReport`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

import pandas as pd

from .cleaning import clean_funding, clean_ohlcv
from .loader import (
    funding_path_for,
    iter_ohlcv_paths,
    load_funding_csv,
    load_ohlcv_csv,
    market_from_ohlcv_path,
)
from .report import FundingReport, IngestReport, MarketReport

logger = logging.getLogger(__name__)


class CacheRepository(Protocol):
    async def replace_candles(
        self, market: str, rows: list[dict], *, exchange: str, resolution: str
    ) -> int: ...

    async def replace_funding(
        self, market: str, rows: list[dict], *, exchange: str
    ) -> int: ...


def _candle_rows(df: pd.DataFrame, *, exchange: str, market: str, resolution: str) -> list[dict]:
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        rows.append(
            {
                "exchange": exchange,
                "market": market,
                "resolution": resolution,
                "timestamp": r.timestamp.to_pydatetime(),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
        )
    return rows


def _funding_rows(df: pd.DataFrame, *, exchange: str, market: str) -> list[dict]:
    return [
        {
            "exchange": exchange,
            "market": market,
            "timestamp": r.timestamp.to_pydatetime(),
            "funding_rate": float(r.funding_rate),
        }
        for r in df.itertuples(index=False)
    ]


async def run_ingest(
    data_dirs: list[str] | list[Path],
    *,
    repo: CacheRepository | None,
    exchange: str = "dydx",
    resolution: str = "1HOUR",
    min_coverage_rows: int,
    drop_flat: bool = True,
    drop_zero_volume: bool = True,
    ingest_funding: bool = True,
    dry_run: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
) -> IngestReport:
    """
    Run the full ingest over ``data_dirs`` and return the validation report.

    When ``dry_run`` is True the cleaning/coverage logic runs and the report is
    built exactly as for a real run, but nothing is written to the cache (and
    ``repo`` may be ``None``); a real run requires a repository.
    """
    if not dry_run and repo is None:
        raise ValueError("run_ingest requires a repo unless dry_run=True")

    paths = iter_ohlcv_paths(data_dirs)
    total = len(paths)
    report = IngestReport(
        min_coverage_rows=min_coverage_rows,
        exchange=exchange,
        resolution=resolution,
        dry_run=dry_run,
    )
    logger.info("Ingesting %d markets from %s", total, [str(d) for d in data_dirs])

    for i, path in enumerate(paths, start=1):
        market = market_from_ohlcv_path(path)
        source_dir = path.parent.name
        if progress:
            progress(i, total, market)

        try:
            raw = load_ohlcv_csv(path)
            clean_df, stats = clean_ohlcv(
                raw, drop_flat=drop_flat, drop_zero_volume=drop_zero_volume
            )
        except Exception as exc:  # a single bad file must not abort the ingest
            logger.warning("Failed to load/clean %s: %s", market, exc)
            from .cleaning import CleaningStats

            empty = CleaningStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            report.markets.append(
                MarketReport(
                    market=market,
                    source_dir=source_dir,
                    stats=empty,
                    included=False,
                    exclusion_reason="load_error",
                )
            )
            continue

        included = stats.clean_rows >= min_coverage_rows and stats.clean_rows > 0
        reason = None
        if not included:
            reason = "no_clean_rows" if stats.clean_rows == 0 else "low_coverage"

        first_ts = last_ts = None
        if stats.clean_rows:
            first_ts = clean_df["timestamp"].iloc[0].isoformat()
            last_ts = clean_df["timestamp"].iloc[-1].isoformat()

        cached = 0
        if included and not dry_run:
            rows = _candle_rows(
                clean_df, exchange=exchange, market=market, resolution=resolution
            )
            cached = await repo.replace_candles(
                market, rows, exchange=exchange, resolution=resolution
            )

        report.markets.append(
            MarketReport(
                market=market,
                source_dir=source_dir,
                stats=stats,
                included=included,
                cached_rows=cached,
                first_ts=first_ts,
                last_ts=last_ts,
                exclusion_reason=reason,
            )
        )
        logger.info(
            "%s: %d/%d clean (%s)%s",
            market,
            stats.clean_rows,
            stats.raw_rows,
            "included" if included else f"excluded:{reason}",
            f" → cached {cached}" if (included and not dry_run) else "",
        )

        # Funding: ingest only for markets we keep, so the cache stays coherent.
        if ingest_funding and included:
            fpath = funding_path_for(path)
            if fpath.exists():
                try:
                    fdf, fraw, fdup = clean_funding(load_funding_csv(fpath))
                    fcached = 0
                    if not dry_run:
                        frows = _funding_rows(fdf, exchange=exchange, market=market)
                        fcached = await repo.replace_funding(market, frows, exchange=exchange)
                    report.funding.append(
                        FundingReport(
                            market=market,
                            source_dir=source_dir,
                            raw_rows=fraw,
                            duplicates_dropped=fdup,
                            clean_rows=len(fdf),
                            cached_rows=fcached,
                        )
                    )
                except Exception as exc:
                    logger.warning("Funding ingest failed for %s: %s", market, exc)

    return report
