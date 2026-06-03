-- CreateEnum
CREATE TYPE "BacktestStatus" AS ENUM ('PENDING', 'RUNNING', 'PAUSED', 'COMPLETED', 'STOPPED', 'FAILED');

-- CreateTable
CREATE TABLE "strategies" (
    "id" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "name" TEXT NOT NULL,
    "description" TEXT,
    "status" "BacktestStatus" NOT NULL DEFAULT 'PENDING',
    "scan_window_days" INTEGER NOT NULL DEFAULT 90,
    "trade_window_days" INTEGER NOT NULL DEFAULT 30,
    "zscore_window" INTEGER NOT NULL DEFAULT 21,
    "entry_threshold" DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    "exit_threshold" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "stop_threshold" DOUBLE PRECISION NOT NULL DEFAULT 4.0,
    "pvalue_max" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "max_half_life_h" DOUBLE PRECISION NOT NULL DEFAULT 72,
    "start_time" TIMESTAMPTZ,
    "end_time" TIMESTAMPTZ,
    "starting_capital" DOUBLE PRECISION NOT NULL DEFAULT 10000,
    "usd_per_trade" DOUBLE PRECISION NOT NULL DEFAULT 100,
    "max_active_pairs" INTEGER,
    "slippage_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "taker_fee_pct" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "funding_freq_h" INTEGER NOT NULL DEFAULT 1,
    "total_windows" INTEGER NOT NULL DEFAULT 0,
    "processed_windows" INTEGER NOT NULL DEFAULT 0,
    "progress" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "current_capital" DOUBLE PRECISION,
    "final_capital" DOUBLE PRECISION,
    "net_pnl" DOUBLE PRECISION,
    "total_trades" INTEGER NOT NULL DEFAULT 0,
    "win_rate" DOUBLE PRECISION,
    "rank" INTEGER,
    "equity_curve" JSONB,
    "per_window" JSONB,
    "per_pair_pnl" JSONB,
    "exit_reasons" JSONB,
    "report_md" TEXT,
    "error" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completed_at" TIMESTAMPTZ,

    CONSTRAINT "strategies_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "strategies_exchange_status_idx" ON "strategies"("exchange", "status");

-- CreateIndex
CREATE INDEX "strategies_rank_idx" ON "strategies"("rank");
