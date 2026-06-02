"""
Central configuration & trading constants — statsArbBot.

All tunable algorithm parameters live here so live trading, simulation,
fast-forward replay, and backtest read a single source of truth. The four
"Option-B" research changes (see research.md / ADR-0002) are encoded as the
defaults below:

  * spread includes the OLS intercept α          (handled in statcore, Phase 1)
  * hard stop-loss at |Z| >= STOP_LOSS_ZSCORE    (4.0)
  * exit at |Z| < EXIT_ZSCORE                     (0.5, replaces zero-crossing)
  * half-life cap tightened to MAX_HALF_LIFE_H    (72h, was 200h)

Environment-driven secrets/URLs are read via python-decouple so the same code
runs locally and in Docker.
"""

from __future__ import annotations

from decouple import config as _env

# ── Environment / infrastructure ─────────────────────────────────────────────
DATABASE_URL: str = _env("DATABASE_URL", default="")
# Shared secret the Next.js proxy injects as `X-API-Key`. Reuses the dashboard
# passcode so there is a single credential to manage in Phase 0.
API_KEY: str = _env("DASHBOARD_PASSWORD", default="changeme")
# testnet (forward_test) | mainnet (production / simulation)
ENVIRONMENT: str = _env("ENVIRONMENT", default="testnet")

# ── Signal thresholds (Option-B) ─────────────────────────────────────────────
ZSCORE_THRESH: float = _env("ZSCORE_THRESH", default=1.5, cast=float)     # entry
EXIT_ZSCORE: float = _env("EXIT_ZSCORE", default=0.5, cast=float)         # exit  (#3)
STOP_LOSS_ZSCORE: float = _env("STOP_LOSS_ZSCORE", default=4.0, cast=float)  # stop (#2)

# ── Pair filter ──────────────────────────────────────────────────────────────
PVALUE_MAX: float = _env("PVALUE_MAX", default=0.05, cast=float)
MAX_HALF_LIFE_H: float = _env("MAX_HALF_LIFE_H", default=72.0, cast=float)  # cap (#4)
# Time-based stop: close any position older than this multiple of half-life (#2)
TIME_STOP_HALF_LIFE_MULT: float = _env("TIME_STOP_HALF_LIFE_MULT", default=3.0, cast=float)

# ── Z-score window ───────────────────────────────────────────────────────────
# Configurable; research.md §3 recommends ~2-3x the median half-life of active
# pairs. Default 21 is a conservative starting point carried from the reference.
ZSCORE_WINDOW: int = _env("ZSCORE_WINDOW", default=21, cast=int)

# ── Sizing & collateral ──────────────────────────────────────────────────────
USD_PER_TRADE: float = _env("USD_PER_TRADE", default=100.0, cast=float)
USD_MIN_COLLATERAL: float = _env("USD_MIN_COLLATERAL", default=1880.0, cast=float)
