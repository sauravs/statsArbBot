# Hyperliquid Integration — Architecture & Implementation Plan

**Date:** 2026-06-14 · **Branch:** `hyperliquid` · **Status:** Planned, not started.

Companion to [`HYPERLIQUID_RESEARCH.md`](./HYPERLIQUID_RESEARCH.md) (the *why*)
and [`HYPERLIQUID_PROGRESS.md`](./HYPERLIQUID_PROGRESS.md) (live status). All
file paths below were verified against the codebase on the branch-creation date.

---

## 0. Build methodology & key decisions

**Vertical slices, not horizontal layers.** Each sub-phase is a thin slice that
runs **end-to-end** (data → cache → engine → visible result) and is **tested on
the local dev Docker stack before** the next slice starts. We do not build the
whole data layer, then the whole engine, then wire at the end — that defers
integration risk. The phased plan in §3 maps onto these slices:

| Slice | End-to-end thread | Done-when (local dev stack) |
|---|---|---|
| 1 — Data read | factory dispatch → cointegration **scan** on live HL data | scan with `SCAN_DATA_SOURCE=hyperliquid` returns real HL pairs in the UI |
| 2 — Backtest/ingest | `make_fetch_client(exchange)` → ingest HL OHLCV+funding → **backtest** | backtest produces results from cached HL data (funding sourced from HL) |
| 3 — Deep history | S3 archive backfill | long-window backtest runs past the ~5k-candle live cap |
| 4 — Trade client | HL trade client (testnet) → **forward-test** mode | place + close a position on HL **testnet** end-to-end |
| 5 — UI venue switch | Trading Context bar + venue/source decouple + theming | switch venue in UI; scan/backtest/trade follow; DEMO/LIVE absorbed |

Registry `integrated=True` flips incrementally: data capability after Slice 2,
trading modes after Slice 4.

**Decision — `SCAN_DATA_SOURCE` (minimal-append, defer decouple).** Adding
Hyperliquid uses a **minimal-append**: extend `VALID_DATA_SOURCES` to
`("fake", "dydx", "hyperliquid")` and turn the factory's `if fake/else dydx` into
an explicit **dispatch map** that fails loudly on an unknown source. The full
venue/data-source **decouple is deferred to Slice 5**, where the Trading Context
bar genuinely needs the modes×exchanges grid — so the refactor pays for itself
instead of being a speculative horizontal change up front (YAGNI / just-in-time).

## 1. Architecture assessment — how pluggable are we today?

**Good:** the foundations exist (ADR-0004 "exchange registry"):
- `backend/exchanges/registry.py` — `EXCHANGE_REGISTRY` already declares
  `hyperliquid` (and `binance`) as `ExchangeInfo(integrated=False, has_testnet=False, live_modes=[])`.
- `backend/prisma/schema.prisma` — `enum Exchange { dydx, binance, hyperliquid }`
  is already present and carried on the relevant tables (`OhlcvCache`,
  `FundingRateCache`, `CointScanResult`, `ManualTrade`, live/sim/strategy tables).
  **No schema migration needed to add Hyperliquid rows.**
- Core engines (statcore, backtest sweep, simulation, live entry/exit, scan
  orchestrator) are **protocol-based** — they depend on the `PriceSource` /
  `trading.broker.TradeClient` interfaces, not on dYdX directly.

**The gap (this is the real work, not a flag-flip):** the client factories in
`backend/exchanges/__init__.py` — `make_data_client()` and `make_trade_client()`
— currently switch **only on `config.SCAN_DATA_SOURCE`** with two outcomes:
`"fake"` → demo clients, anything else → **dYdX** clients. They do **not**
dispatch by exchange. So adding Hyperliquid means teaching the factories (and the
data-source config) to route by venue, not just toggle fake/real.

Supporting hardcodes to address:
- `backend/config.py`: `VALID_DATA_SOURCES = ("fake", "dydx")`,
  `SCAN_DATA_SOURCE` default `"dydx"`, `DEFAULT_EXCHANGE = "dydx"`, and the
  `DYDX_*` indexer/wallet env block.
- `backend/ingest/historical_fetch.py`: `make_fetch_client() -> DydxDataClient`
  is hardcoded to dYdX.
- `ui/lib/api.ts`: `DEFAULT_EXCHANGE = "dydx"` and the fake↔dydx data-source toggle.

**Verdict:** architecture is *genuinely pluggable* at the engine/DB layer; the
coupling is concentrated in the **factory + config + ingest** seam. Blast radius
is contained and well-understood.

---

## 2. Contracts to implement

### 2.1 `PriceSource` (read-only data) — mirror `backend/exchanges/dydx/client.py`
Implement on the new `HyperliquidDataClient`:
- `get_markets() -> dict[str, dict]`
- `get_historical_closes(market, num_pages, now, concurrent) -> list[dict]`
- `fetch_ohlcv_range(market, start, end) -> list[dict]`
- `fetch_funding_range(market, start, end) -> list[dict]`
- `aclose()` + async context manager (`__aenter__`/`__aexit__`)

### 2.2 `TradeClient` (execution) — mirror `backend/exchanges/dydx/trade_client.py`, see `backend/trading/broker.py`
- `place_market_order(market, side, size, reduce_only) -> OrderResult | None`
- `is_open_position(market) -> bool`
- `get_open_positions() -> dict[str, Position]`
- `get_free_collateral() -> float`
- `get_account_equity() -> float`
- `cancel_all_orders() -> None`
- `aclose()`
- async `connect()` classmethod (factory calls `await DydxTradeClient.connect()`)

Use `hyperliquid-python-sdk`; EIP-712 signing; testnet via configurable URL.

---

## 3. Phased plan

### Phase 1 — Hyperliquid data ingest + backtest (venue-consistent, no trading)
1. `backend/exchanges/hyperliquid/client.py` — `HyperliquidDataClient` (PriceSource).
   - Live `candleSnapshot` (respect ~5k-candle cap) + `fundingHistory`
     (7-day windows).
   - Offline backfill from **S3 archive** `s3://hyperliquid-archive/` → build
     candles → feed the existing ingest/cache path.
2. `backend/config.py` — extend `VALID_DATA_SOURCES` to include
   `"hyperliquid"`; add `HYPERLIQUID_*` config (API/info URLs, testnet,
   rate-limit). Consider **decoupling** "data source" from "exchange" so the
   conflation in `SCAN_DATA_SOURCE` stops growing.
3. `backend/exchanges/__init__.py` — make `make_data_client()` dispatch by venue.
4. `backend/ingest/historical_fetch.py` — parameterise `make_fetch_client()` by
   exchange; add a `data/hyperliquid/` ingest dir + a refresh script
   (`backend/scripts/refresh_hyperliquid_data.py`).
5. `backend/exchanges/registry.py` — set Hyperliquid `integrated=True`,
   `has_testnet=True`, populate `live_modes`.
6. Validate: run a scan + backtest against ingested Hyperliquid data; confirm
   funding is sourced from Hyperliquid.

### Phase 2 — Hyperliquid trade client (forward-test / testnet)
7. `backend/exchanges/hyperliquid/trade_client.py` (TradeClient via SDK, testnet).
8. `make_trade_client()` venue dispatch; `HYPERLIQUID_*` wallet/agent-key config
   (gitignored, GitHub Environments for CI/CD — never commit secrets).
9. Wire forward-test mode end-to-end on the **local dev Docker stack**.

### Phase 3 — Manual-trading UI + selector
10. `ui/lib/api.ts` + components: exchange selector, thread `exchange` through
    all calls, retire the hardcoded `DEFAULT_EXCHANGE`.
11. Manual/live routers already accept `exchange` — verify, don't rebuild.

### Phase 4 — docs + tests
12. Tests: Hyperliquid client/trade-client unit + integration (testnet); extend
    `backend/tests/conftest.py` fixtures.
13. New ADR (`docs/adr/0011-*`) recording the venue + venue-consistent-data
    decision; update `BACKTEST_PARAMETER_GUIDE.md` with the Hyperliquid source.

### Deferred (not in this branch)
- Binance research/screening overlay (long-history pair discovery).
- Binance trading integration.

---

## 4. File checklist (blast radius)

**New files**
- `backend/exchanges/hyperliquid/__init__.py`
- `backend/exchanges/hyperliquid/client.py` (PriceSource)
- `backend/exchanges/hyperliquid/trade_client.py` (TradeClient)
- `backend/scripts/refresh_hyperliquid_data.py`
- `data/hyperliquid/` (gitignored CSV/backfill)
- `docs/adr/0011-hyperliquid-venue-and-venue-consistent-data.md`
- `backend/tests/test_hyperliquid_*.py`

**Modify**
- `backend/exchanges/__init__.py` — venue dispatch in both factories
- `backend/exchanges/registry.py` — flip `integrated=True`
- `backend/config.py` — `VALID_DATA_SOURCES`, `HYPERLIQUID_*`, decouple source/exchange
- `backend/.env.example` — Hyperliquid keys/URLs (examples only)
- `backend/ingest/historical_fetch.py` — parameterise `make_fetch_client()`
- `ui/lib/api.ts` (+ components) — exchange selector
- `docs/BACKTEST_PARAMETER_GUIDE.md`

**No change needed (already multi-exchange)**
- `backend/prisma/schema.prisma` (enum + exchange columns present)
- Trading/backtest/simulation engines, scan orchestrator
- `routers/{live,manual,sim,backtest,ff}.py` (already take `exchange`)

---

## 5. Process guardrails (from CLAUDE.md)

- Work on this `hyperliquid` branch; **test end-to-end on the local dev Docker
  stack** (no live staging env exists).
- **Operator approval gates** every merge to `main` and any `main → production`
  promotion. Do not merge without explicit OK.
- production = dYdX mainnet today; a Hyperliquid mainnet go-live is a deliberate,
  separate step — never a deploy side effect.
- Never commit secrets; `.env` stays gitignored.
