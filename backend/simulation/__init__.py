"""
Real-time simulation (PRD F6) — a DB-backed paper-trading engine that ticks on an
APScheduler interval, opening/closing virtual positions on *real* live signals.

Layering mirrors ``trading/`` (Phase 5a): a pure cost model (``costs``), a price
feed that builds per-pair snapshots (``feed``), and a stateless engine
(``engine``) that persists through a repository seam (``db.sim_repository``). The
rolling Z-score comes from the same ``statcore`` path the live bot uses — fixing
the prototype's ``0.02``-std approximation (F6.2).
"""
