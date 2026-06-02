#!/usr/bin/env python
"""
Seed OhlcvCache / FundingRateCache from the copied dYdX historical CSVs.

Phase 2.5 entry point (ADR-0006). Run from the ``backend/`` directory so the
package imports resolve and ``config`` discovers the repo ``.env``:

    cd backend
    python scripts/ingest_historical.py                 # real ingest → DB
    python scripts/ingest_historical.py --dry-run        # report only, no writes
    python scripts/ingest_historical.py --min-coverage 500

The validation report (per-market clean/rejected counts, excluded markets) is
written to ``--report`` (default ``data/ingest_report.md``) and a summary is
printed. ``--dry-run`` needs no database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Allow `python scripts/ingest_historical.py` from the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from ingest.pipeline import run_ingest  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest historical dYdX OHLCV + funding into the cache.")
    p.add_argument("--data-dir", action="append", dest="data_dirs",
                   help="Data directory (repeatable). Defaults to config.HISTORICAL_DATA_DIRS.")
    p.add_argument("--min-coverage", type=int, default=config.INGEST_MIN_COVERAGE_ROWS,
                   help=f"Min clean rows to cache a market (default {config.INGEST_MIN_COVERAGE_ROWS}).")
    p.add_argument("--exchange", default=config.DEFAULT_EXCHANGE)
    p.add_argument("--resolution", default=config.CANDLE_RESOLUTION)
    p.add_argument("--no-funding", action="store_true", help="Skip funding-rate ingest.")
    p.add_argument("--dry-run", action="store_true", help="Build the report; write nothing.")
    p.add_argument("--report", default=config.INGEST_REPORT_PATH, help="Markdown report path.")
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()
    data_dirs = args.data_dirs or config.HISTORICAL_DATA_DIRS

    if args.dry_run:
        repo = None  # not used in dry-run
    else:
        from ingest.cache_repository import get_ohlcv_cache_repository

        repo = get_ohlcv_cache_repository()

    def progress(done: int, total: int, market: str) -> None:
        log.info("[%d/%d] %s", done, total, market)

    report = await run_ingest(
        data_dirs,
        repo=repo,
        exchange=args.exchange,
        resolution=args.resolution,
        min_coverage_rows=args.min_coverage,
        drop_flat=config.INGEST_DROP_FLAT,
        drop_zero_volume=config.INGEST_DROP_ZERO_VOLUME,
        ingest_funding=(config.INGEST_FUNDING and not args.no_funding),
        dry_run=args.dry_run,
        progress=progress,
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_markdown())

    log.info("=" * 60)
    log.info("Ingest %s", "DRY RUN complete" if args.dry_run else "complete")
    log.info("Markets: %d included / %d excluded",
             report.markets_included, report.markets_excluded)
    log.info("OHLCV rows: %d clean of %d raw (dropped %d)",
             report.total_clean_rows, report.total_raw_rows, report.total_dropped_rows)
    log.info("OHLCV rows cached: %d", report.total_cached_rows)
    if report.funding:
        log.info("Funding rows cached: %d", report.total_funding_cached)
    log.info("Report → %s", report_path)
    log.info("=" * 60)

    if not args.dry_run:
        from db.client import close_db

        await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
