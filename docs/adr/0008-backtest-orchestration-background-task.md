# 8. Orchestrate the walk-forward backtest as a background task, not a subprocess

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

PRD F8.2 and PLAN Phase 8 call for "**subprocess** orchestration with progress,
pause, stop, partial save + resume" for the walk-forward backtest. The wording is
carried from the prototype, which ran each backtest as a standalone Python script
launched via `subprocess`, communicating progress through a flat file.

A walk-forward backtest is genuinely CPU-heavy: for each sliding window it re-runs
the cointegration scan (`statsmodels.coint` over a 90-day formation window across
the whole market universe) before trading the test window. That work must not block
the FastAPI event loop, and the run must be controllable (pause/stop) and resumable.

The rest of this rewrite has already established a CPU-offload idiom that meets the
same needs without a separate process:
- the live cointegration scan (`scan.orchestrator`) offloads its pair loop to a
  worker thread via `asyncio.to_thread` while mutating state only on the loop;
- the fast-forward replay (`replay.engine`, Phase 7) runs as a FastAPI
  `BackgroundTasks` job with an in-memory cancel flag and DB-persisted progress.

## Decision

Run the backtest sweep as a **FastAPI background task** and offload each window's
CPU-bound cointegration scan via **`asyncio.to_thread`** — *not* as an OS subprocess.

- **Progress / pause / stop:** in-memory control flags (`BacktestEngine._control`)
  checked at each window boundary, exactly mirroring the FF replay's cancel flag.
- **Partial save + resume:** every window boundary persists the resume cursor
  (`processed_windows`), the carried `current_capital`, and the accumulated
  aggregates (equity curve, per-window summary, per-pair P&L, exit reasons) to the
  `Strategy` row. Because positions are force-closed at every window boundary (the
  next window re-scans and may select different pairs), there is **no open-position
  state to serialise** — the entire resumable state is JSON-serialisable scalars +
  aggregates. A PAUSED run resumes from `processed_windows` with the carried capital
  and accumulators; it never recomputes a finished window.

## Consequences

- Same progress / pause / stop / resume semantics the PRD asks for, with **one less
  moving part**: no IPC, no process lifecycle/zombie management, no second Python
  interpreter and DB pool, no flat-file progress channel. Consistent with the
  Phase-2 scan and Phase-7 replay already in the codebase (one source of truth for
  "how we run CPU-bound background work").
- The single-process model means an API restart abandons an in-flight RUNNING sweep
  (its in-memory control flag and background task are lost); the persisted partial
  state still allows a manual resume, and a future enhancement could auto-resume
  RUNNING rows on startup (as the real-time sim re-registers sessions).
- True process isolation (a crashing backtest cannot touch the API process) is
  forgone. Accepted: the sweep is wrapped so any exception marks the row FAILED
  rather than crashing the worker, and the heavy `statsmodels` work runs in a
  thread, not inline on the loop.
