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

import math
import os
from pathlib import Path

from decouple import config as _env


def _as_bool(value) -> bool:
    """Truthy-string caster (decouple's default bool cast doesn't parse 'false')."""
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# Repo root (config.py lives in backend/, the historical data sits at repo-root data/).
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

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

# Bounds for the runtime signal-threshold setter (issue #74). They mirror the
# per-run sim/ff/backtest form bounds (routers/{sim,ff,backtest}.py) so a chart /
# strategy threshold can't be set outside what a simulation would accept. The
# ordering exit < entry < stop is enforced on top of these in set_signal_thresholds.
ZSCORE_ENTRY_MIN, ZSCORE_ENTRY_MAX = 0.5, 4.0
ZSCORE_EXIT_MIN, ZSCORE_EXIT_MAX = 0.0, 2.0  # exit must be strictly > 0
ZSCORE_STOP_MIN, ZSCORE_STOP_MAX = 1.0, 10.0


def get_signal_thresholds() -> dict:
    """The active Option-B signal thresholds as a JSON-safe dict (issue #74)."""
    return {
        "entry": ZSCORE_THRESH,
        "exit": EXIT_ZSCORE,
        "stop": STOP_LOSS_ZSCORE,
    }


def set_signal_thresholds(entry: float, exit: float, stop: float) -> None:
    """Reassign the Option-B signal thresholds at runtime (issue #74).

    Every consumer reads ``config.ZSCORE_THRESH`` / ``EXIT_ZSCORE`` /
    ``STOP_LOSS_ZSCORE`` at call time — statcore signals, the pair-detail chart
    (``pair_series``), and the live entry/exit path; sim/ff/backtest inherit these
    as per-run form defaults — so this takes effect app-wide without a restart
    (the chart reflects it on its next fetch). Enforces sane per-value bounds and
    the ordering ``exit < entry < stop``; raises ``ValueError`` otherwise.
    Persistence (BotConfigHistory) is the caller's concern — this only mutates
    process state.
    """
    entry, exit, stop = float(entry), float(exit), float(stop)
    if not all(math.isfinite(v) for v in (entry, exit, stop)):
        raise ValueError("thresholds must be finite numbers")
    if not ZSCORE_ENTRY_MIN <= entry <= ZSCORE_ENTRY_MAX:
        raise ValueError(f"entry must be in [{ZSCORE_ENTRY_MIN}, {ZSCORE_ENTRY_MAX}]")
    if not ZSCORE_EXIT_MIN < exit <= ZSCORE_EXIT_MAX:
        raise ValueError(f"exit must be in ({ZSCORE_EXIT_MIN}, {ZSCORE_EXIT_MAX}]")
    if not ZSCORE_STOP_MIN <= stop <= ZSCORE_STOP_MAX:
        raise ValueError(f"stop must be in [{ZSCORE_STOP_MIN}, {ZSCORE_STOP_MAX}]")
    if not (exit < entry < stop):
        raise ValueError("thresholds must satisfy exit < entry < stop")
    global ZSCORE_THRESH, EXIT_ZSCORE, STOP_LOSS_ZSCORE
    ZSCORE_THRESH, EXIT_ZSCORE, STOP_LOSS_ZSCORE = entry, exit, stop

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
# Pages of history fetched per leg for the pair-detail chart (issue #61). Kept
# small (and fetched concurrently) so a live chart loads in seconds rather than
# minutes — ~2 pages ≈ 200 hourly bars ≈ 8 days, enough for the spread/Z window.
PAIR_CHART_PAGES: int = _env("PAIR_CHART_PAGES", default=2, cast=int)
# Max simultaneous candle-fetch requests against the indexer (rate-limit guard).
SCAN_FETCH_CONCURRENCY: int = _env("SCAN_FETCH_CONCURRENCY", default=3, cast=int)
# Process-wide cap on concurrent indexer candle requests across ALL callers
# (scan, pairs-price poll, record snapshot, portfolio mark-to-market, charts) so
# they share one rate budget and never burst the indexer into Retry-After
# throttling (issue #65). The per-caller caps above are secondary to this.
DYDX_INDEXER_MAX_CONCURRENCY: int = _env(
    "DYDX_INDEXER_MAX_CONCURRENCY", default=6, cast=int
)
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

# The market-data sources the runtime toggle (issue #43) may switch between.
VALID_DATA_SOURCES: tuple[str, ...] = ("fake", "dydx")


def set_scan_data_source(value: str) -> None:
    """Reassign the active market-data source at runtime (issue #43).

    Every reader accesses ``config.SCAN_DATA_SOURCE`` at call time
    (``make_data_client`` / ``make_price_source`` / the candle source / the FF
    router), so this takes effect for subsequent requests without a restart. It
    is **not** persisted — the process resets to the ``SCAN_DATA_SOURCE`` env
    default on restart (arguably safer: a restart can't leave a stale override).
    """
    global SCAN_DATA_SOURCE
    if value not in VALID_DATA_SOURCES:
        raise ValueError(f"data source must be one of {VALID_DATA_SOURCES}")
    SCAN_DATA_SOURCE = value

# CSV half of the dual-write (PRD §3.1 step 7). Relative to the backend dir.
COINTEGRATED_PAIRS_CSV: str = _env(
    "COINTEGRATED_PAIRS_CSV", default="data/cointegrated_pairs.csv"
)

# ── Live trading execution (Phase 5a) ────────────────────────────────────────
# dYdX account credentials (used only for order placement / account queries; the
# read-only price layer never needs them). Empty on a data-only deployment.
DYDX_WALLET_ADDRESS: str = _env("DYDX_WALLET_API_KEY", default="")
DYDX_PRIVATE_KEY: str = _env("DYDX_PRIVATE_KEY", default="")
DYDX_SUBACCOUNT_INDEX: int = _env("DYDX_SUBACCOUNT_INDEX", default=0, cast=int)

# Trading network endpoints, selected by ENVIRONMENT (account/orders only — price
# data still always uses the mainnet indexer above). The node URL signs/broadcasts
# on-chain; the REST indexer answers position/collateral queries.
DYDX_MAINNET_NODE_URL: str = _env(
    "DYDX_MAINNET_NODE_URL", default="dydx-ops-grpc.kingnodes.com:443"
)

# Market-order execution params (carried from the reference bot's constants.py).
ORDER_PRICE_BUFFER: float = _env("ORDER_PRICE_BUFFER", default=0.05, cast=float)  # 5%
ORDER_EXPIRY_BLOCKS: int = _env("ORDER_EXPIRY_BLOCKS", default=10, cast=int)
MAX_ORDER_WAIT_SECS: float = _env("MAX_ORDER_WAIT_SECS", default=20.0, cast=float)
ORDER_POLL_INTERVAL: float = _env("ORDER_POLL_INTERVAL", default=3.0, cast=float)

# ── Telegram approval / alerts (Phase 9 — ADR-0009) ──────────────────────────
# When both a bot token and an operator chat id are set, the live engine's
# ApprovalGate + Alerter are swapped for the Telegram-backed implementations at
# startup (see telegrambot/runtime.py). Unset → the AutoApproveGate/LoggingAlerter
# defaults stay, so every other phase keeps running with no human in the loop.
TELEGRAM_BOT_TOKEN: str = _env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_CHAT_ID: str = _env("TELEGRAM_CHAT_ID", default="")
# Minutes to wait for an approve/reject tap before auto-rejecting the signal.
# 0 → reject immediately (a kill-switch: every signal times out unapproved).
TELEGRAM_APPROVAL_TIMEOUT_MIN: float = _env(
    "TELEGRAM_APPROVAL_TIMEOUT_MIN", default=15.0, cast=float
)
# Treat the placeholder values shipped in .env.example as "unset" so a half-filled
# .env doesn't try (and fail) to connect to Telegram on every restart.
_TG_PLACEHOLDERS = {"", "your_bot_token_here", "your_chat_id_here"}
TELEGRAM_ENABLED: bool = (
    TELEGRAM_BOT_TOKEN not in _TG_PLACEHOLDERS
    and TELEGRAM_CHAT_ID not in _TG_PLACEHOLDERS
)


# ── Historical data ingest (Phase 2.5 — ADR-0006) ────────────────────────────
# Directories holding the copied dYdX CSVs, ingested into OhlcvCache/FundingRateCache
# and replayed by Phases 7 (fast-forward) and 8 (backtest). Gitignored, repo-local.
_DEFAULT_DATA_DIRS = os.pathsep.join(
    [str(REPO_ROOT / "data" / "dydx"), str(REPO_ROOT / "data" / "dydx_extended")]
)
HISTORICAL_DATA_DIRS: list[str] = _env(
    "HISTORICAL_DATA_DIRS", default=_DEFAULT_DATA_DIRS
).split(os.pathsep)
# A market must retain at least this many CLEAN hourly bars to be cached.
# Default 2160 = 90 days, the walk-forward backtest's scan-window length (Phase 8),
# so every cached market can fill at least one full formation window.
INGEST_MIN_COVERAGE_ROWS: int = _env("INGEST_MIN_COVERAGE_ROWS", default=2160, cast=int)
INGEST_DROP_FLAT: bool = _env("INGEST_DROP_FLAT", default=True, cast=_as_bool)
INGEST_DROP_ZERO_VOLUME: bool = _env("INGEST_DROP_ZERO_VOLUME", default=True, cast=_as_bool)
INGEST_FUNDING: bool = _env("INGEST_FUNDING", default=True, cast=_as_bool)

# Max span (days) a single UI-triggered historical-data fetch may cover (issue
# #81). Caps indexer load — a longer history is fetched in a couple of passes.
DATA_FETCH_MAX_DAYS: int = _env("DATA_FETCH_MAX_DAYS", default=366, cast=int)
# Validation report destination (markdown). Gitignored under data/.
INGEST_REPORT_PATH: str = _env(
    "INGEST_REPORT_PATH", default=str(REPO_ROOT / "data" / "ingest_report.md")
)
