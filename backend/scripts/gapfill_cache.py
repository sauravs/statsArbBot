#!/usr/bin/env python
"""
Top up OhlcvCache (+funding) to the present from the dYdX mainnet indexer.

Resumable, idempotent maintenance job. For every market dYdX currently lists it
reads the last cached candle and fetches ONLY the missing tail [last+1h, now] in
``<= DATA_FETCH_MAX_DAYS`` chunks, merging by range (``_fetch_one`` never deletes
on empty). Run from the ``backend/`` directory so imports resolve and ``config``
discovers the repo ``.env``:

    cd backend
    python scripts/gapfill_cache.py                 # top up all active markets
    python scripts/gapfill_cache.py --dry-run        # show the plan, fetch nothing
    python scripts/gapfill_cache.py --max-passes 10

It is safe to re-run (each run resumes from what's already cached) and resilient
to disconnects: it retries per market and, between passes, waits out an internet
outage — verified via a BTC sentinel — rather than declaring a false completion
on empty fetches. It stops when every active market is current (``need=0``) or
when the remaining count plateaus across passes (the rest are within publish-lag
or delisted).

Markets dYdX no longer lists (delisted / dropped from the liquid set) keep their
historical rows but cannot be extended — they are reported and skipped.

Complements ``scripts/refresh_dydx_data.py`` (CSV refresh); this one writes the
live DB cache directly. See docs/CICD.md / docs/DEPLOYMENT.md for the cache role.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python scripts/gapfill_cache.py` from the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from ingest.cache_repository import get_ohlcv_cache_repository  # noqa: E402
from ingest.historical_fetch import (  # noqa: E402
    MarketResult,
    _fetch_one,
    make_fetch_client,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gapfill")

_ORIGIN = datetime(2024, 1, 1, tzinfo=timezone.utc)  # earliest we ever backfill


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Top up the OHLCV cache to now from dYdX.")
    p.add_argument("--max-passes", type=int, default=40,
                   help="Max resume passes before giving up (default 40).")
    p.add_argument("--max-staleness-hours", type=int, default=26,
                   help="A market needs filling if its last bar is older than this "
                        "(default 26h, so normal indexer publish-lag is not counted).")
    p.add_argument("--offline-wait", type=int, default=120,
                   help="Seconds to wait between passes when the sentinel says offline.")
    p.add_argument("--dry-run", action="store_true", help="Show the plan; fetch nothing.")
    return p.parse_args()


async def _last_ts(repo, market: str, now: datetime) -> datetime | None:
    rows = await repo.get_candles(
        market, exchange=config.DEFAULT_EXCHANGE,
        resolution=config.CANDLE_RESOLUTION, start=_ORIGIN, end=now,
    )
    if not rows:
        return None
    ts = rows[-1]["timestamp"]  # get_candles returns ascending by timestamp
    return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts


def _chunks(start: datetime, end: datetime, max_days: int):
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=max_days), end)
        yield cur, nxt
        cur = nxt


async def _plan(repo, tickers: list[str], now: datetime, max_staleness: timedelta):
    """Markets whose last cached bar is older than the staleness window."""
    behind: list[tuple[str, datetime]] = []
    for t in tickers:
        last = await _last_ts(repo, t, now)
        frm = (last + timedelta(hours=1)) if last else _ORIGIN
        if frm < now - max_staleness:
            behind.append((t, frm))
    return behind


async def _sentinel_ok(client) -> bool:
    """BTC is always listed; an empty fetch means the internet is down (so a small
    `need` would be a lie). Used to avoid false completion during an outage."""
    now = datetime.now(timezone.utc)
    try:
        probe = await client.fetch_ohlcv_range("BTC-USD", now - timedelta(days=3), now)
        return bool(probe)
    except Exception:  # noqa: BLE001
        return False


async def _one_pass(client, repo, args) -> tuple[int, bool]:
    """One resume pass. Returns (markets still behind after the pass, sentinel_ok)."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    max_staleness = timedelta(hours=args.max_staleness_hours)
    tickers = sorted((await client.get_markets()).keys())

    behind = await _plan(repo, tickers, now, max_staleness)
    log.info("plan: %d market(s) behind: %s", len(behind), [m for m, _ in behind])
    if args.dry_run:
        return len(behind), True

    for i, (market, frm) in enumerate(behind, 1):
        for c0, c1 in _chunks(frm, now, config.DATA_FETCH_MAX_DAYS):
            res = MarketResult(market=market)
            try:
                await _fetch_one(client, repo, market, c0, c1, res)
                log.info("  [%d/%d] %s %s→%s bars=%d fund=%d %s",
                         i, len(behind), market, f"{c0:%Y-%m-%d}", f"{c1:%Y-%m-%d}",
                         res.bars, res.funding_rows, res.status)
            except Exception as exc:  # noqa: BLE001 — one market can't sink the run
                log.warning("  [%d/%d] %s %s→%s ERROR %s",
                            i, len(behind), market, f"{c0:%Y-%m-%d}", f"{c1:%Y-%m-%d}", exc)

    still = await _plan(repo, tickers, now, max_staleness)
    return len(still), await _sentinel_ok(client)


async def _main() -> int:
    args = _parse_args()
    repo = get_ohlcv_cache_repository()
    client = make_fetch_client()
    prev, stable = -1, 0
    try:
        async with client:
            for p in range(args.max_passes):
                log.info("===== pass %d =====", p)
                need, sentinel = await _one_pass(client, repo, args)
                if args.dry_run:
                    log.info("dry-run: %d market(s) would be filled", need)
                    break
                if not sentinel:
                    log.warning("internet appears DOWN — waiting %ds then resuming",
                                args.offline_wait)
                    await asyncio.sleep(args.offline_wait)
                    continue  # do not advance the plateau counter while offline
                if need == 0:
                    log.info("COMPLETE — all active markets current")
                    break
                stable = stable + 1 if need == prev else 0
                prev = need
                if stable >= 3:
                    log.info("need plateaued at %d (online) — remainder is within "
                             "publish-lag or delisted; stopping", need)
                    break
                await asyncio.sleep(5)
            else:
                log.warning("hit --max-passes (%d) without converging", args.max_passes)
    finally:
        from db.client import close_db

        await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
