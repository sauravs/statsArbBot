#!/usr/bin/env python
"""
Refresh the dYdX historical OHLCV + funding CSVs from the mainnet indexer.

Ported (and trimmed to dYdX-only) from the prototype's ``01_download_data.py`` /
``01b_download_dydx_extended.py``. This is the **reproducible refresh path** for
the data that Phase 2.5 ingests — it is NOT run as part of the phase (the data is
already on disk; re-extraction is slow and rate-limited — see ADR-0006). Run it
manually only when you need to extend the date range or add markets:

    cd backend
    python scripts/refresh_dydx_data.py --start 2024-01-01 --end 2025-12-31
    python scripts/refresh_dydx_data.py --discover    # add new liquid markets

After refreshing, re-run ``scripts/ingest_historical.py`` to re-seed the cache.

Binance is intentionally out of scope this phase (the prototype's Binance
download lives in the reference tree; reintroduce it when Binance is implemented).
"""

from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

DYDX_INDEXER = "https://indexer.dydx.trade"
DYDX_CANDLE_LIMIT = 100
MIN_LIQUIDITY_USD = 10_000

# data/dydx is the canonical "Group A" dir; data/dydx_extended holds discovered
# additions. Resolve relative to the repo root (backend/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DYDX_DIR = REPO_ROOT / "data" / "dydx"
EXTENDED_DIR = REPO_ROOT / "data" / "dydx_extended"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("refresh")


def _retry_get(url: str, params: dict | None = None, max_tries: int = 5,
               timeout: float = 30.0) -> httpx.Response:
    """GET with exponential back-off on 429 / connection errors."""
    for attempt in range(max_tries):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, params=params)
            if r.status_code == 429:
                wait = 2 ** attempt + random.uniform(0.5, 1.5)
                log.warning("429 on %s – sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            wait = 2 ** attempt + random.uniform(0.5, 1.5)
            log.warning("Network error (%s) – retry in %.1fs", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"All {max_tries} attempts failed for {url}")


def download_ohlcv(market: str, start: datetime, end: datetime, out_dir: Path) -> None:
    """Paginate 1h candles backwards from ``end`` to ``start`` and save to CSV."""
    out_path = out_dir / f"{market}_ohlcv_1h.csv"
    url = f"{DYDX_INDEXER}/v4/candles/perpetualMarkets/{market}"
    frames: list[pd.DataFrame] = []
    cursor_end = end
    iteration = 0

    while cursor_end > start:
        from_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_iso = cursor_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        log.info("  [OHLCV] %s  %s → %s", market, from_iso[:10], to_iso[:10])
        try:
            r = _retry_get(url, params={"resolution": "1HOUR", "fromISO": from_iso,
                                        "toISO": to_iso, "limit": DYDX_CANDLE_LIMIT})
        except Exception as exc:
            log.warning("  fetch failed for %s: %s", market, exc)
            break

        data = r.json().get("candles", [])
        if not data:
            break

        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["startedAt"], utc=True)
        for col in ["open", "high", "low", "close", "baseTokenVolume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        df = df.rename(columns={"baseTokenVolume": "volume"})
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        frames.append(df)

        earliest = df["timestamp"].min()
        if earliest <= pd.Timestamp(start):
            break
        cursor_end = earliest.to_pydatetime().replace(tzinfo=timezone.utc)
        iteration += 1
        if iteration > 500:
            log.warning("  pagination limit reached for %s", market)
            break
        time.sleep(0.5)

    if not frames:
        log.warning("  No OHLCV data for %s", market)
        return
    combined = (pd.concat(frames, ignore_index=True)
                .sort_values("timestamp").drop_duplicates("timestamp"))
    combined = combined[(combined["timestamp"] >= pd.Timestamp(start)) &
                        (combined["timestamp"] <= pd.Timestamp(end))]
    out_dir.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False)
    log.info("  Saved %d rows → %s", len(combined), out_path.name)


def download_funding(market: str, start: datetime, end: datetime, out_dir: Path) -> None:
    """Fetch historical funding (dYdX charges hourly) paginated by block height."""
    out_path = out_dir / f"{market}_funding.csv"
    url = f"{DYDX_INDEXER}/v4/historicalFunding/{market}"
    frames: list[pd.DataFrame] = []
    cursor_before: str | None = None
    iteration = 0

    while True:
        params: dict = {"limit": 100}
        if cursor_before:
            params["effectiveBeforeOrAtHeight"] = cursor_before
        try:
            r = _retry_get(url, params=params)
        except Exception as exc:
            log.warning("  funding fetch failed for %s: %s", market, exc)
            break

        data = r.json().get("historicalFunding", [])
        if not data:
            break
        raw_df = pd.DataFrame(data)
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(raw_df["effectiveAt"], utc=True),
            "funding_rate": raw_df["rate"].astype(float),
        })
        frames.append(df)

        if df["timestamp"].min() <= pd.Timestamp(start):
            break
        if "effectiveAtHeight" in raw_df.columns:
            cursor_before = str(int(raw_df["effectiveAtHeight"].min()) - 1)
        else:
            break
        iteration += 1
        if iteration > 500:
            log.warning("  funding pagination limit for %s", market)
            break
        time.sleep(0.4)

    if not frames:
        log.warning("  No funding data for %s", market)
        return
    combined = (pd.concat(frames, ignore_index=True)
                .sort_values("timestamp").drop_duplicates("timestamp"))
    combined = combined[(combined["timestamp"] >= pd.Timestamp(start)) &
                        (combined["timestamp"] <= pd.Timestamp(end))]
    out_dir.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False)
    log.info("  Saved %d funding rows → %s", len(combined), out_path.name)


def existing_markets() -> set[str]:
    markets: set[str] = set()
    for d in (DYDX_DIR, EXTENDED_DIR):
        if d.is_dir():
            markets |= {p.name.replace("_ohlcv_1h.csv", "")
                        for p in d.glob("*_ohlcv_1h.csv")}
    return markets


def discover_new_markets() -> list[str]:
    """Live market list, $10K volume filter, minus markets already on disk."""
    r = _retry_get(f"{DYDX_INDEXER}/v4/perpetualMarkets", params={"limit": 200})
    mkts = r.json().get("markets", {})
    already = existing_markets()
    new: list[tuple[str, float]] = []
    for ticker, info in mkts.items():
        if info.get("status") != "ACTIVE":
            continue
        try:
            vol = float(info.get("volume24H", 0))
        except (TypeError, ValueError):
            vol = 0.0
        if vol >= MIN_LIQUIDITY_USD and ticker not in already:
            new.append((ticker, vol))
    new.sort(key=lambda x: -x[1])
    log.info("Discovered %d new liquid markets", len(new))
    return [t for t, _ in new]


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh dYdX historical data (not run by Phase 2.5).")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--discover", action="store_true",
                        help="Discover & download new liquid markets into data/dydx_extended.")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if args.discover:
        targets = [(m, EXTENDED_DIR) for m in discover_new_markets()]
    else:
        targets = [(m, DYDX_DIR) for m in sorted(existing_markets())]

    for market, out_dir in targets:
        ohlcv_path = out_dir / f"{market}_ohlcv_1h.csv"
        funding_path = out_dir / f"{market}_funding.csv"
        if not (args.skip_existing and ohlcv_path.exists()):
            download_ohlcv(market, start, end, out_dir)
        if not (args.skip_existing and funding_path.exists()):
            download_funding(market, start, end, out_dir)

    log.info("Refresh complete. Re-run scripts/ingest_historical.py to re-seed the cache.")


if __name__ == "__main__":
    main()
