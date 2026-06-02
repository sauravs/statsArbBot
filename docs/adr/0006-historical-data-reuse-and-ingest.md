# 6. Reuse existing historical data; ingest into a gitignored `data/` dir with validation

- **Status:** Accepted
- **Date:** 2026-06-02

## Context

Backtesting (Phase 8) and fast-forward simulation (Phase 7) need historical hourly candles + funding. The prototype already contains extracted dYdX data under `Old Reference Resources/oldCodeRef_Prototype/backtest/data/`:

- `dydx/` — ~31 markets (OHLCV + funding).
- `dydx_extended/` — 10 curated markets (AAVE, ARB, ATH, BONK, DYM, ETC, INJ, PAXG, STRK, WOO), range **2024-02-13 → 2025-12-30**, ~16,476 hourly rows each.
- `binance/` — ~207 markets (out of scope this phase).
- Total ~213 MB.

`Old Reference Resources/` is gitignored. Re-extracting this history from the dYdX v4 indexer is slow, rate-limited, and risks gaps for older ranges — with no upside since the data is already real and on disk. Inspection also revealed flat / zero-volume candles (OHLC all equal, `volume=0`) that would distort cointegration and inflate backtest results if used raw.

## Decision

1. **Reuse, do not re-extract.** Consume the existing dYdX data.
2. **Scope:** ingest **both `dydx` and `dydx_extended`** (dYdX only; Binance excluded this phase).
3. **Location:** copy the dYdX CSVs into a new repo-local `data/` directory, which is **gitignored** (large, regenerable). The new codebase reads from `data/`, not from `Old Reference Resources/`, so it is self-contained even if the reference folder is removed.
4. **Validation/cleaning pass** on ingest: drop or flag zero-volume / flat candles, detect and handle gaps, enforce a minimum-coverage threshold per market; ingest seeds the `OhlcvCache` table.
5. **Keep an extraction script** (ported from the prototype's `01_download_data.py`) for reproducible refresh, even though it is not run now. Data currently ends 2025-12-30; "recent" validation fetches live.

## Consequences

- No fragile re-download; backtests run on known-good local data.
- Backtest/FF results are more trustworthy because dirty candles are removed up front (addresses a prototype credibility gap).
- A one-time copy step duplicates ~213 MB locally; acceptable and gitignored.
- Adds a small **data-ingest + validation sub-phase** (Phase 2.5 in `PLAN.md`) feeding Phases 7 and 8.
