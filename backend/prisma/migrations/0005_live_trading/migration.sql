-- CreateEnum
CREATE TYPE "LiveTradeStatus" AS ENUM ('PENDING', 'OPEN', 'CLOSED', 'ERROR');

-- CreateTable
CREATE TABLE "live_sessions" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "mode" "TradingMode" NOT NULL,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "started_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "stopped_at" TIMESTAMPTZ,

    CONSTRAINT "live_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "live_trades" (
    "id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "mode" "TradingMode" NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "base_side" TEXT NOT NULL,
    "quote_side" TEXT NOT NULL,
    "base_size" DOUBLE PRECISION NOT NULL,
    "quote_size" DOUBLE PRECISION NOT NULL,
    "hedge_ratio" DOUBLE PRECISION NOT NULL,
    "half_life" DOUBLE PRECISION NOT NULL,
    "entry_z_score" DOUBLE PRECISION NOT NULL,
    "entry_price_leg1" DOUBLE PRECISION NOT NULL,
    "entry_price_leg2" DOUBLE PRECISION NOT NULL,
    "status" "LiveTradeStatus" NOT NULL DEFAULT 'PENDING',
    "opened_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "exit_z_score" DOUBLE PRECISION,
    "exit_price_leg1" DOUBLE PRECISION,
    "exit_price_leg2" DOUBLE PRECISION,
    "exit_reason" TEXT,
    "pnl" DOUBLE PRECISION,
    "closed_at" TIMESTAMPTZ,
    "error" TEXT,

    CONSTRAINT "live_trades_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "live_sessions_exchange_mode_active_idx" ON "live_sessions"("exchange", "mode", "active");

-- CreateIndex
CREATE INDEX "live_trades_exchange_mode_status_idx" ON "live_trades"("exchange", "mode", "status");

-- CreateIndex
CREATE INDEX "live_trades_session_id_idx" ON "live_trades"("session_id");

-- AddForeignKey
ALTER TABLE "live_trades" ADD CONSTRAINT "live_trades_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "live_sessions"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
