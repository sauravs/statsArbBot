"""
Cointegrated pairs endpoints.

  GET /api/pairs?exchange=&mode=                     — the latest scan's pairs,
      read from the CointScanResult table so results survive a reload / API
      restart (PRD F2.3).
  GET /api/pairs/{base}/{quote}/series?exchange=&mode=  — the per-pair chart
      series (normalized overlay, spread + σ bands, rolling Z-score + entry/exit
      markers) backing the 3-panel pair-detail view (PRD F3, Phase 3).

Reads the DB half of the scan's dual-write; the CSV half is for inspection only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import config
from auth import require_api_key
from db.scan_repository import get_scan_repository
from exchanges import make_data_client
from manual.repository import get_manual_trade_repository
from marketdata.pair_series import build_pair_series, current_prices

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/api/pairs")
async def get_pairs(
    exchange: str | None = Query(default=None),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    # Default to the venue of the active data source (e.g. hyperliquid when the
    # source is HL), not a hardcoded dydx, so the table follows the selected venue.
    exchange = exchange or config.active_exchange()
    try:
        pairs = await get_scan_repository().get_latest_pairs(
            exchange=exchange, mode=mode
        )
    except Exception as exc:
        # Stay 200 so the dashboard renders before the first scan, but surface
        # the failure via `error` (and log at error level) so a DB outage is not
        # silently indistinguishable from "no scan run yet".
        logger.error("get_pairs DB read failed: %s", exc)
        return {
            "pairs": [],
            "count": 0,
            "scanned_at": None,
            "exchange": exchange,
            "mode": mode,
            "error": "Could not read pairs from the database.",
        }

    scanned_at = pairs[0]["scanned_at"] if pairs else None
    total = len(pairs)
    # Read-time list minimisation (Phase-3 WS2): enrich each pair with a tradability
    # score + max-leg half-spread, then apply the operator's runtime half-spread
    # ceiling + top-N cap. Non-destructive (the stored scan is untouched) and OFF by
    # default → identity. A tractability lens, NOT an alpha lever.
    try:
        from scan.list_view import minimised_pairs

        pairs = await minimised_pairs(
            pairs, exchange=exchange, scanned_at=scanned_at, mode=mode
        )
    except Exception as exc:  # never fail the list on an enrichment hiccup
        logger.warning("pair-list minimisation skipped (kept full list): %s", exc)
    return {
        "pairs": pairs,
        "count": len(pairs),
        # Total found before the read-time filters, so the UI can show "N of M".
        "total": total,
        "scanned_at": scanned_at,
        "exchange": exchange,
        "mode": mode,
        "filters": config.get_scan_list_filters(),
        "error": None,
    }


@router.get("/api/pairs/prices")
async def get_pair_prices(
    exchange: str | None = Query(default=None),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    """
    Current price (latest close) for every market in the latest scan's pairs
    (issue #37 PR-2). A light read — each unique market fetched once — meant to
    be polled by the dashboard alongside the pairs table.

    Stays 200 with ``prices: {}`` + an ``error`` string on a DB / fetch failure
    so the table still renders (prices just show "—").
    """
    exchange = exchange or config.active_exchange()
    try:
        pairs = await get_scan_repository().get_latest_pairs(exchange=exchange, mode=mode)
    except Exception as exc:
        logger.error("get_pair_prices DB read failed: %s", exc)
        return {"prices": {}, "error": "Could not read pairs from the database."}

    markets = [m for p in pairs for m in (p["base_market"], p["quote_market"])]
    if not markets:
        return {"prices": {}, "error": None}

    client = make_data_client()
    try:
        prices = await current_prices(client, markets)
    except Exception as exc:
        logger.error("get_pair_prices fetch failed: %s", exc)
        return {"prices": {}, "error": "Could not fetch current prices."}
    finally:
        try:
            await client.aclose()
        except Exception as exc:  # must not mask a real result/error
            logger.warning("data client close failed: %s", exc)

    return {"prices": prices, "error": None}


@router.get("/api/pairs/{base}/{quote}/series")
async def get_pair_series(
    base: str,
    quote: str,
    exchange: str | None = Query(default=None),
    mode: str = Query(default=config.DEFAULT_MODE),
) -> dict:
    """
    Chart series for one cointegrated pair (PRD F3).

    The pair's β/α/half-life come from the latest scan, so the chart's spread
    matches what the scan computed. If the pair has rolled out of the latest scan
    it falls back to the pair's most recent **recorded manual trade** (issue #137)
    — a manual trade is a durable record whose chart must keep rendering for its
    life, even after the ephemeral scan no longer lists the pair. The fallback
    reuses the trade's stored β/half-life (intercept defaults to 0.0, which leaves
    the rolling Z-score unchanged); only a pair that was never scanned *and* never
    traded 404s. Prices are fetched from the configured data source (live dYdX, or
    the demo source under ``SCAN_DATA_SOURCE=fake``) and assembled into three panels.
    """
    exchange = exchange or config.active_exchange()
    try:
        record = await get_scan_repository().get_pair(
            exchange=exchange, mode=mode, base_market=base, quote_market=quote
        )
    except Exception as exc:
        logger.error("get_pair_series DB read failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not read pairs from the database.")

    if record is None:
        # Not in the latest scan — fall back to a recorded manual trade for this
        # pair so its chart still renders (issue #137). Scoped to the active data
        # source so a demo trade's chart uses demo params, a live trade's live.
        try:
            record = await get_manual_trade_repository().get_latest_for_pair(
                exchange=exchange,
                mode=mode,
                base_market=base,
                quote_market=quote,
                data_source=config.SCAN_DATA_SOURCE,
            )
        except Exception as exc:
            logger.error("get_pair_series manual fallback read failed: %s", exc)
            raise HTTPException(
                status_code=503, detail="Could not read trades from the database."
            )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pair {base}/{quote} not found in the latest scan or recorded trades.",
        )

    client = make_data_client()
    try:
        series = await build_pair_series(
            client,
            base_market=base,
            quote_market=quote,
            hedge_ratio=record["hedge_ratio"],
            # A manual-trade fallback row has no intercept (α); default to 0.0,
            # which leaves the rolling Z-score unchanged (a constant spread shift).
            intercept=record.get("intercept", 0.0) or 0.0,
            half_life=record.get("half_life"),
            # Fast path (issue #61): a small, concurrently-fetched page count so a
            # live chart loads in seconds instead of minutes (full-history fetch).
            num_pages=config.PAIR_CHART_PAGES,
            concurrent=True,
        )
    finally:
        try:
            await client.aclose()
        except Exception as exc:  # must not mask a real result/error
            logger.warning("data client close failed: %s", exc)

    if series is None:
        raise HTTPException(
            status_code=404,
            detail=f"No overlapping price history for {base}/{quote}.",
        )
    return series.to_dict()
