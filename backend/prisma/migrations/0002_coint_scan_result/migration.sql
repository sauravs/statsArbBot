-- CreateTable
CREATE TABLE "coint_scan_results" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "mode" "TradingMode" NOT NULL,
    "scanned_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "window_start" TIMESTAMPTZ NOT NULL,
    "window_end" TIMESTAMPTZ NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "hedge_ratio" DOUBLE PRECISION NOT NULL,
    "intercept" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "half_life" DOUBLE PRECISION NOT NULL,
    "zero_crossings" INTEGER NOT NULL,
    "p_value" DOUBLE PRECISION NOT NULL,
    "z_score" DOUBLE PRECISION,
    "spread_std" DOUBLE PRECISION,

    CONSTRAINT "coint_scan_results_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "coint_scan_results_exchange_mode_scanned_at_idx" ON "coint_scan_results"("exchange", "mode", "scanned_at");

-- CreateIndex
CREATE INDEX "coint_scan_results_base_market_quote_market_idx" ON "coint_scan_results"("base_market", "quote_market");
