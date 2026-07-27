-- Backend strategy-campaign runner (Phase-3 WS3). ADDITIVE + non-destructive:
-- a new campaigns table + a nullable campaigns FK on strategies. Every existing
-- strategy row keeps campaign_id NULL (hand-created); nothing is deleted or mutated.
-- ON DELETE SET NULL means deleting a campaign never deletes its member runs.

-- CreateEnum
CREATE TYPE "CampaignStatus" AS ENUM ('PENDING', 'RUNNING', 'PAUSED', 'DONE', 'STOPPED');

-- CreateTable
CREATE TABLE "campaigns" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "exchange" "Exchange" NOT NULL DEFAULT 'dydx',
    "data_source" TEXT NOT NULL DEFAULT 'dydx',
    "status" "CampaignStatus" NOT NULL DEFAULT 'PENDING',
    "spec" JSONB NOT NULL,
    "concurrency" INTEGER NOT NULL DEFAULT 2,
    "total" INTEGER NOT NULL DEFAULT 0,
    "completed" INTEGER NOT NULL DEFAULT 0,
    "failed" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" TIMESTAMPTZ,
    "ended_at" TIMESTAMPTZ,

    CONSTRAINT "campaigns_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "campaigns_status_idx" ON "campaigns"("status");

-- AlterTable
ALTER TABLE "strategies" ADD COLUMN "campaign_id" TEXT;

-- CreateIndex
CREATE INDEX "strategies_campaign_id_idx" ON "strategies"("campaign_id");

-- AddForeignKey
ALTER TABLE "strategies" ADD CONSTRAINT "strategies_campaign_id_fkey" FOREIGN KEY ("campaign_id") REFERENCES "campaigns"("id") ON DELETE SET NULL ON UPDATE CASCADE;
