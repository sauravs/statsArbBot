-- CreateTable
CREATE TABLE "ohlcv_cache" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "market" TEXT NOT NULL,
    "resolution" TEXT NOT NULL DEFAULT '1HOUR',
    "timestamp" TIMESTAMPTZ NOT NULL,
    "open" DOUBLE PRECISION NOT NULL,
    "high" DOUBLE PRECISION NOT NULL,
    "low" DOUBLE PRECISION NOT NULL,
    "close" DOUBLE PRECISION NOT NULL,
    "volume" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "ohlcv_cache_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "funding_rate_cache" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "market" TEXT NOT NULL,
    "timestamp" TIMESTAMPTZ NOT NULL,
    "funding_rate" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "funding_rate_cache_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ohlcv_cache_exchange_market_resolution_timestamp_idx" ON "ohlcv_cache"("exchange", "market", "resolution", "timestamp");

-- CreateIndex
CREATE UNIQUE INDEX "ohlcv_cache_exchange_market_resolution_timestamp_key" ON "ohlcv_cache"("exchange", "market", "resolution", "timestamp");

-- CreateIndex
CREATE INDEX "funding_rate_cache_exchange_market_timestamp_idx" ON "funding_rate_cache"("exchange", "market", "timestamp");

-- CreateIndex
CREATE UNIQUE INDEX "funding_rate_cache_exchange_market_timestamp_key" ON "funding_rate_cache"("exchange", "market", "timestamp");
