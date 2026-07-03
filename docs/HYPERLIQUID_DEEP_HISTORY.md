# Hyperliquid deep history + cache top-ups (ops)

How the Hyperliquid (HL) OHLCV/funding cache is backfilled with multi-year history
and kept current. Companion scripts live in [`../ops/`](../ops/). These are
**box-side operational scripts** (they drive the running Docker stack via
`docker compose exec` and the local `/api/data/fetch` endpoint), not app modules.

> **Status:** ops scripts, validated on the production box (2026-07-02). A future
> refactor could fold the deep-archive path into `backend/ingest/` proper (reuse
> the cleaning pipeline + `cache_repository`, add tests). Tracked as a follow-up.

## Why this exists — the live-API limit

HL's `/info` `candleSnapshot` returns only the **most recent ~5,000 candles
regardless of `startTime`** (any fully-past window returns empty). At 1h resolution
that's ~208 days (~7 months). So the live indexer **cannot** backfill hourly history
older than ~7 months. Deep history comes from HL's **S3 archive** instead.

## Deep backfill — `ops/hl_deep_backfill.py`

**Source:** `s3://hyperliquid-archive/asset_ctxs/YYYYMMDD.csv.lz4` — per-coin,
**per-minute** rows: `time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,
premium,oracle_px,mark_px,mid_px,...` (back to 2023-05-20). We aggregate `mid_px`
into hourly OHLC (open=first minute, close=last minute, high/low), carry
`day_ntl_vlm` as volume, and sample `funding` hourly. Rows are **UPSERTed**
(`ON CONFLICT (exchange,market,resolution,timestamp) DO UPDATE`) into
`ohlcv_cache` / `funding_rate_cache` — non-destructive, deletes nothing.

**Cost:** the bucket is **requester-pays in `us-east-1`**. Run it **on the EC2 box
(same region) → S3→EC2 transfer is free**; only trivial request charges (~$1). The
heavy `market_data/` L2 dataset (~1 TB) is **not** needed — `asset_ctxs` (~5 GB
total) has everything for candles.

**Prerequisites (on the box):** `aws` CLI, `lz4`, the Docker stack up, and an
**instance IAM role with `AmazonS3ReadOnlyAccess`** (the box already has the
`statsarb-s3-read` role). No access keys — auth is via the instance role.

**Run (resumable):**
```bash
# on the box, in ~/statsArbBot
python3 ops/hl_deep_backfill.py --validate 20260620 20260626   # compare vs live closes, no writes
python3 ops/hl_deep_backfill.py --run 20240101 20251204        # backfill the gap (default range)
```
Resumable via `~/hl_deep_backfill.done` (one `YYYYMMDD` per committed day); re-running
skips done days. **Take a `pg_dump` first.** Validation (2026-07-02) showed the
archive's mid-based closes track the live trade-based candles within **~0.03–0.05%**
(BTC/ETH/SOL).

**Data caveats:** prices are **mid-based** OHLC (not trade-based); **volume is a
24h-notional proxy** (`day_ntl_vlm`) since the archive has no trades feed — fine for
cointegration (close-price) and funding-based P&L, but not a true per-bar volume.

## Keeping the cache current — `ops/topup.sh` (cron)

`ops/topup.sh <dydx|hyperliquid> [days]` fires a rolling, non-destructive
`/api/data/fetch` for the recent tail (default 12 days) and logs to `ops/topup.log`.
It reads the API key from `.env` at runtime (no secret embedded).

Installed on the box as `/etc/cron.d/statsarb-topup` (daily, staggered):
```cron
0 2 * * * ubuntu /home/ubuntu/statsArbBot/ops/topup.sh dydx 12
0 3 * * * ubuntu /home/ubuntu/statsArbBot/ops/topup.sh hyperliquid 12
```
Disable by removing that file. Complements the dYdX-only
[`backend/scripts/gapfill_cache.py`](../backend/scripts/gapfill_cache.py) (which
`topup.sh` supersedes for cron use since it is venue-aware).
