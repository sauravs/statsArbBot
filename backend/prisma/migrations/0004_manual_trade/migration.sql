-- CreateEnum
CREATE TYPE "ManualTradeStatus" AS ENUM ('OPEN', 'CLOSED');

-- CreateTable
CREATE TABLE "manual_trades" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "mode" "TradingMode" NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "hedge_ratio" DOUBLE PRECISION NOT NULL,
    "half_life" DOUBLE PRECISION NOT NULL,
    "z_score" DOUBLE PRECISION NOT NULL,
    "spread_value" DOUBLE PRECISION NOT NULL,
    "entry_price_leg1" DOUBLE PRECISION NOT NULL,
    "entry_price_leg2" DOUBLE PRECISION NOT NULL,
    "capital_leg1_usd" DOUBLE PRECISION NOT NULL,
    "capital_leg2_usd" DOUBLE PRECISION NOT NULL,
    "recorded_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "status" "ManualTradeStatus" NOT NULL DEFAULT 'OPEN',
    "closed_at" TIMESTAMPTZ,
    "exit_price_leg1" DOUBLE PRECISION,
    "exit_price_leg2" DOUBLE PRECISION,
    "pnl" DOUBLE PRECISION,

    CONSTRAINT "manual_trades_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "manual_trades_exchange_mode_status_idx" ON "manual_trades"("exchange", "mode", "status");

-- CreateIndex
CREATE INDEX "manual_trades_recorded_at_idx" ON "manual_trades"("recorded_at");
