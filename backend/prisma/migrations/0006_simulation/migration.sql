-- CreateEnum
CREATE TYPE "SimSessionStatus" AS ENUM ('RUNNING', 'PAUSED', 'STOPPED');

-- CreateEnum
CREATE TYPE "SimPositionStatus" AS ENUM ('OPEN', 'CLOSED');

-- CreateTable
CREATE TABLE "sim_sessions" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "mode" "TradingMode" NOT NULL DEFAULT 'simulation',
    "label" TEXT,
    "status" "SimSessionStatus" NOT NULL DEFAULT 'RUNNING',
    "starting_capital" DOUBLE PRECISION NOT NULL,
    "current_capital" DOUBLE PRECISION NOT NULL,
    "interval_seconds" INTEGER NOT NULL DEFAULT 60,
    "zscore_window" INTEGER NOT NULL DEFAULT 21,
    "entry_threshold" DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    "exit_threshold" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "stop_threshold" DOUBLE PRECISION NOT NULL DEFAULT 4.0,
    "usd_per_trade" DOUBLE PRECISION NOT NULL DEFAULT 100,
    "max_active_pairs" INTEGER,
    "slippage_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "taker_fee_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "funding_freq_h" INTEGER NOT NULL DEFAULT 1,
    "tick_count" INTEGER NOT NULL DEFAULT 0,
    "last_tick_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "stopped_at" TIMESTAMPTZ,

    CONSTRAINT "sim_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sim_positions" (
    "id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "direction" TEXT NOT NULL,
    "base_size" DOUBLE PRECISION NOT NULL,
    "quote_size" DOUBLE PRECISION NOT NULL,
    "hedge_ratio" DOUBLE PRECISION NOT NULL,
    "half_life" DOUBLE PRECISION NOT NULL,
    "entry_z" DOUBLE PRECISION NOT NULL,
    "entry_base_px" DOUBLE PRECISION NOT NULL,
    "entry_quote_px" DOUBLE PRECISION NOT NULL,
    "entry_time" TIMESTAMPTZ NOT NULL,
    "fee_cost" DOUBLE PRECISION NOT NULL,
    "funding_pnl" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "status" "SimPositionStatus" NOT NULL DEFAULT 'OPEN',

    CONSTRAINT "sim_positions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sim_trades" (
    "id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL,
    "base_market" TEXT NOT NULL,
    "quote_market" TEXT NOT NULL,
    "direction" TEXT NOT NULL,
    "entry_time" TIMESTAMPTZ NOT NULL,
    "exit_time" TIMESTAMPTZ NOT NULL,
    "hold_hours" DOUBLE PRECISION NOT NULL,
    "entry_z" DOUBLE PRECISION NOT NULL,
    "exit_z" DOUBLE PRECISION,
    "exit_reason" TEXT NOT NULL,
    "notional_usd" DOUBLE PRECISION NOT NULL,
    "gross_pnl" DOUBLE PRECISION NOT NULL,
    "fee_cost" DOUBLE PRECISION NOT NULL,
    "funding_pnl" DOUBLE PRECISION NOT NULL,
    "net_pnl" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "sim_trades_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "sim_sessions_exchange_mode_status_idx" ON "sim_sessions"("exchange", "mode", "status");

-- CreateIndex
CREATE INDEX "sim_positions_session_id_status_idx" ON "sim_positions"("session_id", "status");

-- CreateIndex
CREATE INDEX "sim_trades_session_id_idx" ON "sim_trades"("session_id");

-- CreateIndex
CREATE INDEX "sim_trades_exchange_entry_time_idx" ON "sim_trades"("exchange", "entry_time");

-- AddForeignKey
ALTER TABLE "sim_positions" ADD CONSTRAINT "sim_positions_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "sim_sessions"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sim_trades" ADD CONSTRAINT "sim_trades_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "sim_sessions"("id") ON DELETE CASCADE ON UPDATE CASCADE;
