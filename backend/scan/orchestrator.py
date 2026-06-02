"""
Cointegration scan orchestrator.

Pipeline (PRD §3.1):
  1. Build the historical close-price matrix for all eligible markets.
  2. For every unique pair, run ``statcore.analyze_pair`` (the single source of
     statistical truth — Engle-Granger, OLS hedge ratio **with intercept**, spread,
     OU half-life, Option-B filters). The CPU-bound pair loop is offloaded to a
     worker thread in chunks via ``asyncio.to_thread`` so the event loop stays
     responsive; scan state is mutated only on the loop, never from the thread.
  3. Dual-write survivors to CSV and the ``CointScanResult`` table.

Concurrency safety: the caller claims the scan with ``ScanState.try_begin()``
before launching this coroutine, so only one scan runs at a time.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config
from db.scan_repository import get_scan_repository
from marketdata.price_matrix import build_price_matrix
from scan.state import SCAN_STATE, ScanState
from statcore import analyze_pair, compute_spread, latest_zscore

logger = logging.getLogger(__name__)

# Pairs analysed per worker-thread hand-off (balances responsiveness vs overhead).
_CHUNK_SIZE = 200
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _csv_path() -> Path:
    p = Path(config.COINTEGRATED_PAIRS_CSV)
    return p if p.is_absolute() else _BACKEND_DIR / p


def _analyze_chunk(
    df: pd.DataFrame,
    pairs: list[tuple[str, str]],
    *,
    pvalue_max: float,
    max_half_life: float,
    min_rows: int,
) -> tuple[int, list[dict]]:
    """
    Analyse a chunk of pairs (runs in a worker thread). Returns
    ``(tested, found_rows)`` where ``found_rows`` are dicts for survivors only.
    """
    found: list[dict] = []
    for base, quote in pairs:
        s1 = df[base].to_numpy(dtype=float)
        s2 = df[quote].to_numpy(dtype=float)
        if len(s1) < min_rows:
            continue

        # A single degenerate series (flat/collinear prices that clear the candle
        # minimum) can make statsmodels raise inside coint()/OLS. Isolate it per
        # pair so one bad market never aborts the whole scan (the reference bot
        # wrapped its equivalent in a bare try/except for the same reason).
        try:
            analysis = analyze_pair(
                s1, s2, pvalue_max=pvalue_max, max_half_life=max_half_life
            )
            if not analysis.passes_filter:
                continue

            spread = compute_spread(s1, s2, analysis.hedge_ratio, analysis.intercept)
            z = latest_zscore(spread, window=config.ZSCORE_WINDOW)
        except Exception as exc:  # noqa: BLE001 — skip the pair, keep the scan alive
            logger.warning("pair %s/%s analysis failed: %s", base, quote, exc)
            continue

        found.append(
            {
                "base_market": base,
                "quote_market": quote,
                "hedge_ratio": analysis.hedge_ratio,
                "intercept": analysis.intercept,
                "half_life": analysis.half_life,
                "zero_crossings": analysis.zero_crossings,
                "p_value": analysis.p_value,
                "z_score": None if not np.isfinite(z) else float(z),
                "spread_std": float(np.std(spread, ddof=1)),
            }
        )
    return len(pairs), found


def _write_csv(found: list[dict]) -> None:
    """Write survivors to CSV (the inspection half of the dual-write)."""
    path = _csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "base_market", "quote_market", "hedge_ratio", "intercept",
        "half_life", "zero_crossings", "p_value", "z_score", "spread_std",
    ]
    df = pd.DataFrame(found, columns=columns)
    if not df.empty:
        # Deterministic, matching the DB read order: best quality first, p-value
        # as a stable tie-break so CSV and /api/pairs agree on row order.
        df.sort_values(
            ["zero_crossings", "p_value"], ascending=[False, True], inplace=True
        )
    df.to_csv(path, index=False)


async def run_scan(
    *,
    client=None,
    repository=None,
    state: ScanState = SCAN_STATE,
    quick: bool = False,
    num_pages: int | None = None,
    exchange: str | None = None,
    mode: str | None = None,
    now=None,
) -> dict:
    """
    Execute one cointegration scan and dual-write the results.

    Assumes the caller has already claimed the scan via ``state.try_begin()``.
    Always settles the state (``finish`` or ``fail``) before returning.
    """
    repository = repository or get_scan_repository()
    exchange = exchange or config.DEFAULT_EXCHANGE
    mode = mode or config.DEFAULT_MODE
    pages = num_pages or (config.SCAN_QUICK_PAGES if quick else config.NUM_HISTORICAL_PAGES)

    own_client = client is None
    if own_client:
        if config.SCAN_DATA_SOURCE == "fake":
            from exchanges.demo import DemoDataClient

            client = DemoDataClient()
        else:
            from exchanges.dydx.client import DydxDataClient

            client = DydxDataClient()

    try:
        state.set_phase(2, "Fetching market data…")

        def _market_cb(done: int, total: int) -> None:
            state.update_markets(done, total)
            state.progress_msg = f"Fetching market data: {done}/{total} markets"

        matrix = await build_price_matrix(
            client, num_pages=pages, progress_callback=_market_cb, now=now
        )

        if matrix.is_empty:
            state.finish("No market data returned from indexer.")
            return {"found": 0, "tested": 0}

        markets = list(matrix.df.columns)
        n = len(markets)
        total_pairs = n * (n - 1) // 2
        state.update_pairs(0, total_pairs, 0)
        state.set_phase(3, f"Testing {n} markets ({total_pairs:,} pairs)…")

        min_rows = config.ZSCORE_WINDOW + 10

        # Generate pairs lazily; only one chunk is materialised at a time.
        pair_iter = itertools.combinations(markets, 2)
        tested = 0
        found: list[dict] = []
        while True:
            chunk = list(itertools.islice(pair_iter, _CHUNK_SIZE))
            if not chunk:
                break
            chunk_tested, chunk_found = await asyncio.to_thread(
                _analyze_chunk,
                matrix.df,
                chunk,
                pvalue_max=config.PVALUE_MAX,
                max_half_life=config.MAX_HALF_LIFE_H,
                min_rows=min_rows,
            )
            tested += chunk_tested
            found.extend(chunk_found)
            pct = tested / total_pairs * 100 if total_pairs else 100.0
            state.update_pairs(tested, total_pairs, len(found))
            state.progress_msg = (
                f"Pairs: {tested:,}/{total_pairs:,} ({pct:.1f}%) — "
                f"{len(found)} cointegrated"
            )

        # ── dual-write ────────────────────────────────────────────────────────
        # The DB is the authoritative store /api/pairs reads, so write it first;
        # the CSV (inspection copy) is written only after the DB succeeds so the
        # two halves can never diverge on a DB failure.
        scanned_at = now or datetime.now(timezone.utc)
        rows = [
            {
                **row,
                "exchange": exchange,
                "mode": mode,
                "scanned_at": scanned_at,
                "window_start": matrix.window_start,
                "window_end": matrix.window_end,
            }
            for row in found
        ]
        try:
            await repository.replace_scan_results(rows, exchange=exchange, mode=mode)
        except Exception as exc:
            logger.error("DB dual-write failed: %s", exc)
            state.fail(f"Scan computed {len(found)} pairs but DB write failed: {exc}")
            return {"found": len(found), "tested": tested, "db_error": str(exc)}

        # Off the event loop — for a large survivor set / slow disk the to_csv
        # write must not stall concurrent /api/scan/status polls.
        await asyncio.to_thread(_write_csv, found)

        state.finish(
            f"✓ Complete — {len(found)} cointegrated pair(s) "
            f"from {tested:,}/{total_pairs:,} tested."
        )
        return {"found": len(found), "tested": tested}

    except Exception as exc:  # noqa: BLE001 — scan must never crash the server
        logger.exception("Scan failed")
        state.fail(str(exc))
        return {"found": 0, "tested": 0, "error": str(exc)}
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception as exc:  # must not mask the scan's real outcome
                logger.warning("data client close failed: %s", exc)
