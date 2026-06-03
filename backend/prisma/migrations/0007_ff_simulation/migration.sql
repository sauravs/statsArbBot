-- CreateEnum
CREATE TYPE "FFSimStatus" AS ENUM ('RUNNING', 'COMPLETED', 'STOPPED', 'FAILED');

-- CreateTable
CREATE TABLE "saved_ff_simulations" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "label" TEXT,
    "status" "FFSimStatus" NOT NULL DEFAULT 'RUNNING',
    "start_time" TIMESTAMPTZ NOT NULL,
    "end_time" TIMESTAMPTZ NOT NULL,
    "speed" INTEGER NOT NULL DEFAULT 3600,
    "zscore_window" INTEGER NOT NULL DEFAULT 21,
    "entry_threshold" DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    "exit_threshold" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "stop_threshold" DOUBLE PRECISION NOT NULL DEFAULT 4.0,
    "usd_per_trade" DOUBLE PRECISION NOT NULL DEFAULT 100,
    "max_active_pairs" INTEGER,
    "slippage_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "taker_fee_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "funding_freq_h" INTEGER NOT NULL DEFAULT 1,
    "pairs_count" INTEGER NOT NULL DEFAULT 0,
    "total_ticks" INTEGER NOT NULL DEFAULT 0,
    "processed_ticks" INTEGER NOT NULL DEFAULT 0,
    "progress" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "starting_capital" DOUBLE PRECISION NOT NULL,
    "final_capital" DOUBLE PRECISION,
    "realised_pnl" DOUBLE PRECISION,
    "total_trades" INTEGER NOT NULL DEFAULT 0,
    "equity_curve" JSONB,
    "per_pair_pnl" JSONB,
    "exit_reasons" JSONB,
    "error" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completed_at" TIMESTAMPTZ,

    CONSTRAINT "saved_ff_simulations_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "saved_ff_simulations_exchange_status_idx" ON "saved_ff_simulations"("exchange", "status");

-- CreateIndex
CREATE INDEX "saved_ff_simulations_created_at_idx" ON "saved_ff_simulations"("created_at");
