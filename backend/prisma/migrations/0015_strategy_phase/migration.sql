-- Provenance tag (Phase-2 Slice 6): which project phase created each backtest
-- strategy. 1 = phase-1 baseline (the saved configs preserved as the honest
-- baseline); 2 = phase-2 (sub-phase B onward). ADDITIVE and non-destructive — every
-- existing row is backfilled to phase 1 by the NOT NULL DEFAULT; no row is deleted
-- or otherwise mutated. New runs are stamped 2 by the create path.
ALTER TABLE "strategies" ADD COLUMN "phase" INTEGER NOT NULL DEFAULT 1;
