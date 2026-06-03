"""
Fast-forward simulation (PRD F7) — replay historical OHLCV at N× speed through
the *same* statistical engine the real-time sim and live bot use.

Layers (mirroring ``simulation/``):
  * :mod:`replay.candle_source` — where the historical bars come from
    (``OhlcvCache`` in production, deterministic demo series offline).
  * :mod:`replay.historical_feed` — turn aligned per-pair closes at a replay
    cursor into ``simulation.feed.PairTick`` snapshots + per-bar funding rates.
  * :mod:`replay.working_repo` — an in-memory ledger satisfying the repo
    interface ``simulation.run_tick`` writes to (a batch run doesn't persist
    every intermediate position to Postgres; only the aggregates are saved).
  * :mod:`replay.engine` — :class:`FastForwardReplayEngine`, the orchestrator the
    router launches as a background task; it walks the cursor, ticks the engine,
    samples equity, and persists the ``SavedFFSimulation`` aggregate.
"""
