-- CreateEnum
CREATE TYPE "Exchange" AS ENUM ('dydx', 'binance', 'hyperliquid');

-- CreateEnum
CREATE TYPE "TradingMode" AS ENUM ('forward_test', 'simulation', 'production');

-- CreateTable
CREATE TABLE "BotConfigHistory" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "mode" "TradingMode" NOT NULL DEFAULT 'forward_test',
    "key" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "changed_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BotConfigHistory_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "BotConfigHistory_exchange_mode_idx" ON "BotConfigHistory"("exchange", "mode");

