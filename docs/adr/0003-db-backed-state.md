# 3. DB-backed state instead of flat files

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The prototype persisted live trading and signal state in flat JSON files (`bot_agents.json`, `pending_signals.json`). This caused race conditions, lost state on crashes between write points, and reconciliation drift against the exchange. PostgreSQL (via Prisma) is already in the stack.

## Decision

All live, simulation, fast-forward, manual-trade, and signal state is persisted in PostgreSQL through Prisma. No flat-file persistence for runtime state. Shared in-process state needed during scans/backtests is guarded with explicit async concurrency primitives (locks/queues), not assumed safe because of the event loop. Prisma client generation is wired into the Docker build and the FastAPI lifespan so the generated client can never drift from the schema (eliminating the `FieldNotFoundError`/HTTP 503 class of bugs).

## Consequences

- Crash-safe, queryable, reconcilable state; no JSON race conditions.
- A running PostgreSQL instance is required in all environments (already true via Docker Compose).
- Slightly more ceremony (migrations, client generation) — offset by eliminating an entire class of prototype bugs.
