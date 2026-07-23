-- Seed the OHLCV cache so the Data-inventory e2e spec has coverage to report.
--
-- The cache is only ever written by the historical ingest, which talks to a real
-- exchange indexer — so a fresh database (CI, or any clean checkout) has none, and
-- `data.spec.ts` asserted on a market count that could only be non-zero if someone
-- had previously run an ingest by hand. That made the spec pass on a developer's
-- machine and fail everywhere else.
--
-- These are synthetic hourly bars for two demo markets, deliberately shaped like
-- real ones (a gentle sine drift, high/low bracketing the close) so the inventory's
-- completeness percentage is a meaningful number rather than a degenerate one.
--
-- Idempotent: ON CONFLICT DO NOTHING against the (exchange, market, resolution,
-- timestamp) unique key, so re-running it is safe.

INSERT INTO ohlcv_cache (id, exchange, market, resolution, timestamp, open, high, low, close, volume)
SELECT
    'e2e-seed-' || m.market || '-' || g.i                       AS id,
    'dydx'::"Exchange"                                          AS exchange,
    m.market                                                    AS market,
    '1HOUR'                                                     AS resolution,
    -- A contiguous 168-hour (7 day) window ending at the most recent whole hour,
    -- so coverage is complete and its end is always "recent" regardless of when
    -- the suite runs.
    date_trunc('hour', now()) - ((167 - g.i) * INTERVAL '1 hour') AS timestamp,
    m.base + 10 * sin(g.i / 12.0)                               AS open,
    m.base + 10 * sin(g.i / 12.0) + 5                           AS high,
    m.base + 10 * sin(g.i / 12.0) - 5                           AS low,
    m.base + 10 * sin((g.i + 1) / 12.0)                         AS close,
    1000 + g.i                                                  AS volume
FROM generate_series(0, 167) AS g(i)
CROSS JOIN (VALUES ('BTC-USD', 60000.0), ('ETH-USD', 3000.0)) AS m(market, base)
ON CONFLICT (exchange, market, resolution, timestamp) DO NOTHING;
