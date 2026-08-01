-- Link a real-time simulation session to the saved Strategy it paper-trades (Phase 5).
--
-- ADDITIVE and non-destructive: one NULLABLE column, NULL on every existing row
-- (a hand-created session mirrors no strategy). Lets the dashboard highlight which
-- strategy is currently live in simulation, and lets a session say what it mirrors.
--
-- ON DELETE SET NULL — deleting a strategy must never cascade into simulation data,
-- and the link must never make a strategy row harder to remove. (Strategy rows are
-- the project's evidence and are never deleted in practice; this is belt-and-braces.)
ALTER TABLE "sim_sessions" ADD COLUMN "source_strategy_id" TEXT;

CREATE INDEX "sim_sessions_source_strategy_id_idx" ON "sim_sessions"("source_strategy_id");

ALTER TABLE "sim_sessions"
  ADD CONSTRAINT "sim_sessions_source_strategy_id_fkey"
  FOREIGN KEY ("source_strategy_id") REFERENCES "strategies"("id")
  ON DELETE SET NULL ON UPDATE CASCADE;
