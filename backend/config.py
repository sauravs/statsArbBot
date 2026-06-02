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
# testnet (forward_test) | mainnet (production / simulation)
ENVIRONMENT: str = _env("ENVIRONMENT", default="testnet")

# Shared secret the Next.js proxy injects as `X-API-Key`. Reuses the dashboard
# passcode so there is a single credential to manage in Phase 0. The weak
# "changeme" default is tolerated only on testnet; on mainnet an unset passcode
# is a hard error (otherwise the backend would accept a publicly-known key).
_DASHBOARD_PASSWORD: str = _env("DASHBOARD_PASSWORD", default="")
if not _DASHBOARD_PASSWORD and ENVIRONMENT != "testnet":
    raise RuntimeError(
        "DASHBOARD_PASSWORD must be set when ENVIRONMENT is not 'testnet'"
    )
API_KEY: str = _DASHBOARD_PASSWORD or "changeme"

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

# ── dYdX market-data layer (Phase 2) ─────────────────────────────────────────
# Account/order operations follow ENVIRONMENT; price/candle data ALWAYS uses the
# mainnet indexer for real liquidity & volume (testnet markets are sparse). This
# mirrors the reference bot's split (shared.py: INDEXER_URL vs DATA_INDEXER_URL).
DYDX_MAINNET_INDEXER: str = _env(
    "DYDX_MAINNET_INDEXER", default="https://indexer.dydx.trade"
)
DYDX_TESTNET_INDEXER: str = _env(
    "DYDX_TESTNET_INDEXER", default="https://indexer.v4testnet.dydx.exchange"
)
# Indexer used for the cointegration scan's historical candles (real liquidity).
DYDX_DATA_INDEXER: str = DYDX_MAINNET_INDEXER

CANDLE_RESOLUTION: str = _env("CANDLE_RESOLUTION", default="1HOUR")
CANDLES_PER_PAGE: int = _env("CANDLES_PER_PAGE", default=100, cast=int)
# Pages of history fetched per market for the full scan (~100h each at 1HOUR).
NUM_HISTORICAL_PAGES: int = _env("NUM_HISTORICAL_PAGES", default=4, cast=int)
# Pages used for a quick/timed scan.
SCAN_QUICK_PAGES: int = _env("SCAN_QUICK_PAGES", default=2, cast=int)
# Max simultaneous candle-fetch requests against the indexer (rate-limit guard).
SCAN_FETCH_CONCURRENCY: int = _env("SCAN_FETCH_CONCURRENCY", default=3, cast=int)
# Minimum candles a market must have to be included in the price matrix.
MIN_CANDLES_PER_MARKET: int = _env("MIN_CANDLES_PER_MARKET", default=50, cast=int)

# Market eligibility filters.
MIN_LIQUIDITY_USD: float = _env("MIN_LIQUIDITY_USD", default=10_000.0, cast=float)
STABLECOIN_KEYWORDS: tuple[str, ...] = (
    "USDC", "USDT", "DAI", "BUSD", "TUSD",
    "FRAX", "LUSD", "USDD", "USDP", "PYUSD",
)

# Default exchange/mode the scan writes under (Phase 2 implements dYdX only).
DEFAULT_EXCHANGE: str = _env("DEFAULT_EXCHANGE", default="dydx")
DEFAULT_MODE: str = _env("DEFAULT_MODE", default="forward_test")

# Scan data source: "dydx" hits the live mainnet indexer; "fake" uses the
# deterministic in-process DemoDataClient (offline dev, demos, and E2E tests so
# the scan does not depend on the network or take minutes). See exchanges/demo.py.
SCAN_DATA_SOURCE: str = _env("SCAN_DATA_SOURCE", default="dydx")

# CSV half of the dual-write (PRD §3.1 step 7). Relative to the backend dir.
COINTEGRATED_PAIRS_CSV: str = _env(
    "COINTEGRATED_PAIRS_CSV", default="data/cointegrated_pairs.csv"
)
