# Hyperliquid Integration — Progress Tracker

**Branch:** `hyperliquid` (off `main`) · **Started:** 2026-06-14

Living status doc for future agents. See
[`HYPERLIQUID_RESEARCH.md`](./HYPERLIQUID_RESEARCH.md) (why) and
[`HYPERLIQUID_PLAN.md`](./HYPERLIQUID_PLAN.md) (how / file checklist).

---

## Decisions locked
- **Venue:** Hyperliquid (mirrors dYdX v4: DEX + EIP-712; no KYC; no US geo-block).
- **Backtest data:** **Hyperliquid-native** (price + funding) — venue-consistent.
  Solve the ~5k-candle live cap via the S3 archive backfill.
- **Binance:** deferred — future *optional* research/screening overlay only;
  no Binance trading integration planned.
- **Branch name:** `hyperliquid`.
- **UI placement (UX):** **Trading Context bar** — a persistent full-width strip
  under the header (Phase 3). Segmented venue switcher (dYdX / Hyperliquid /
  Binance-disabled), venue **color-themes the page accent** (indigo ↔ teal), and
  shows venue + mode + equity together. Absorbs today's section `DEMO/LIVE`
  control (`DataSourceControl.tsx`). Chosen for trading-team intuition +
  venue-mistake safety (answers "what venue / live-or-demo / how much capital"
  in one glance).

## Status board

| # | Item | Status |
|---|------|--------|
| 0 | Research + venue/data decision | ✅ Done |
| 0 | Branch `hyperliquid` created | ✅ Done |
| 0 | Docs (research / plan / progress) | ✅ Done |
| 1 | `HyperliquidDataClient` (PriceSource: markets/closes/ohlcv/funding) | ✅ Done (5 tests green) |
| 1 | Config: `HYPERLIQUID_*` endpoints + concurrency | ✅ Done |
| 1 | Config: `VALID_DATA_SOURCES` += `hyperliquid` (decouple deferred to Slice 5) | ✅ Done |
| 1 | `make_data_client()` venue dispatch (+ `make_trade_client` rejects HL) | ✅ Done (4 tests green) |
| 1 | **Validate scan on live HL data** (local dev stack) | ✅ PASS — see note ⚠️ exchange-stamp bug |
| 2 | Ingest: parameterise `make_fetch_client(exchange)` + thread `exchange` through fetch/data router | ✅ Done (3 tests green) |
| 2 | Registry: HL `integrated=True` (data-only; `live_modes=[]`) + live-trade guard | ✅ Done (live-reject test) |
| 2 | **Validate ingest + backtest on live HL data** (local dev stack) | ✅ PASS — see Slice 2 note |
| 3 | Deep history via S3 archive backfill (also lets a trade fire → exercises HL funding) | ⬜ |
| 4 | `HyperliquidTradeClient` (TradeClient, testnet) + `make_trade_client` dispatch + wallet config | ⬜ |
| 4 | Forward-test e2e on local dev stack | ⬜ |
| 5 | UI Trading Context bar + venue/source decouple | ⬜ |
| 5 | ADR-0011 + guide updates | ⬜ |

Legend: ✅ done · 🔶 in progress · ⬜ not started

## Slice 1 e2e validation (2026-06-14, local dev stack)
Rebuilt `api` with `SCAN_DATA_SOURCE=hyperliquid`, `/api/system/health` →
`data_source: hyperliquid`. Quick scan finished in ~81s → **1930 pairs over live
Hyperliquid markets** (coin-name IDs `0G`/`AAVE`/`kPEPE`/`kSHIB`, the `k`-prefix is
HL's 1000× naming; **zero** dYdX `-USD` tickers). Data path **PASS**. Stack
restored to the `fake` baseline afterwards.

⚠️→✅ **Bug found AND fixed — exchange mislabel.** `scan/orchestrator.py` stamped
every scan row `DEFAULT_EXCHANGE` (`dydx`) regardless of the live source, so HL
pairs were written `exchange=dydx`. **Fixed** with `config.active_exchange()`
(`dydx→dydx`, `hyperliquid→hyperliquid`, `fake→DEFAULT_EXCHANGE`, read at call
time); the scan now stamps that. **Re-verified in the live stack:** post-fix HL
scan wrote **1986 pairs all stamped `hyperliquid`** (`?exchange=hyperliquid`),
while the pre-fix run's 1930 `dydx`-mislabeled rows linger in the dev DB (cleanup
optional — a real dYdX scan overwrites them). 3 unit tests added. Full venue/source
decouple (UI) is still Slice 5; this is the minimal write-side fix.

## Slice 2 validation (2026-06-14, local dev stack)
Threaded `exchange` through the ingest job (`make_fetch_client(exchange)`,
`historical_fetch._run/_fetch_one`, row writers) and the data router
(`/api/data/fetch` + `/api/data/inventory` take `exchange`, registry-validated).
Flipped HL `integrated=True` (data-only, `live_modes=[]`) and added a
`live_modes` guard in `routers/live.py` so a HL live start is cleanly 422'd
(can't reach `make_trade_client`).

**Ingest e2e PASS:** `POST /api/data/fetch {exchange:hyperliquid}` ingested **all
179 HL markets** for both a 5-day and a 60-day window → cache holds real HL OHLCV
+ funding under `exchange=hyperliquid` (`/api/data/inventory?exchange=hyperliquid`;
60-day ≈ 1,441 bars + 1,440 funding rows per market).

⚠️ **Correction to first attempt.** The initial backtest "validation" was run with
`SCAN_DATA_SOURCE=fake` and therefore read **DEMO** data, not the HL cache — because
`replay/candle_source.make_candle_source` returns `DemoCandleSource()` whenever the
global toggle is `fake`, *ignoring* the strategy's exchange (and `DemoCandleSource`
has **no funding** at all). **By design, `fake` mode is fully offline/demo;** to
backtest real HL data the runtime must be in a live mode. In any non-fake mode the
backtest correctly reads `OhlcvCacheSource(exchange=strategy.exchange)`.

**Backtest e2e PASS (redone in `hyperliquid` mode):** a 60-day backtest
(`exchange=hyperliquid`, 30d scan / 10d trade) **COMPLETED with 7,335 trades over
Hyperliquid-coin pairs** (`2Z/S`, `ACE/W`, `ADA/W`, …), full exit lifecycle
(TAKE_PROFIT / STOP_LOSS_ZSCORE / STOP_LOSS_TIME / END_OF_WINDOW). **Funding
proven sourced from HL:** `make_candle_source(exchange='hyperliquid').get_funding`
(the cost-model path) returned **1,440/1,440 non-zero** real HL hourly rates for
ADA. Venue-consistent funding confirmed.

**Key gap for Slice 5:** the backtest replay source is gated by the global
`SCAN_DATA_SOURCE` toggle, not per-strategy — so in `fake` mode an HL strategy
*silently* backtests demo data. The venue/source decouple (Slice 5) should let a
strategy read its own exchange's cache regardless of the global toggle.

Stack restored to `fake` baseline. HL cache rows + a few smoke-test strategies
remain in the dev DB (harmless).

## Open questions / risks
- **Source/exchange decoupling:** `SCAN_DATA_SOURCE` conflates "data source"
  (fake vs live) with "which exchange". Decide whether to split cleanly now or
  extend the enum minimally. Plan §1/§3 leans toward decoupling.
- **S3 archive shape:** archive is L2/asset-contexts, not pre-baked OHLCV — must
  aggregate to candles. Confirm format + a backfill script before relying on it.
- **Funding windowing:** `fundingHistory` truncates long ranges — fetch in
  ~7-day windows.
- **SDK version:** pin `hyperliquid-python-sdk` (≥ v0.18.0) and confirm testnet URL.

## Next action (recommend: defer Slice 3, do Slice 4 or 5)
Funding-on-trade is now **proven without S3** — the live `/info` API returns ~5,000
bars/request (~208 days at 1h), and a 60-day fetch already fired 7,335 trades with
HL funding. **Slice 3 (S3 archive) only buys history beyond ~208 days** (multi-year
studies) and is heavy (lz4 + L2→candle aggregation + AWS). Recommend **deferring
Slice 3** until a multi-year backtest is actually needed, and proceeding to:
  * **Slice 4** — HL trade client (testnet) for forward-test, the next user-facing
    capability; or
  * **Slice 5** — UI Trading Context bar + the venue/source decouple, which also
    closes the "fake-mode silently backtests demo" gap above.

## Changelog
- 2026-06-14 — Research complete; venue + venue-consistent-data decision locked;
  `hyperliquid` branch + planning docs created.
- 2026-06-14 — Phase 1: `HyperliquidDataClient` (read-only `/info` adapter —
  `get_markets`, `get_historical_closes`, `fetch_ohlcv_range`, `fetch_funding_range`)
  normalising Hyperliquid's native shapes onto the dYdX-shaped keys the ingest path
  reads; `HYPERLIQUID_*` config added; 5 unit tests green
  (`tests/test_hyperliquid_client.py`). Committed `d5f677e`.
- 2026-06-14 — Slice 1 wiring: `make_data_client()` → explicit dispatch map
  (fake/dydx/hyperliquid, raises on unknown); `make_trade_client()` explicitly
  rejects `hyperliquid` (NotImplementedError) until Slice 4 so HL data can be live
  without ever routing HL orders to dYdX; `VALID_DATA_SOURCES` += `hyperliquid`;
  4 factory tests green (`tests/test_exchange_factory.py`). Full suite: 361 passed,
  14 failed — the 14 are **pre-existing on `main`** (local env, not this change).
  **Next: operator runs a scan with `SCAN_DATA_SOURCE=hyperliquid` on the local
  dev stack to validate Slice 1 end-to-end.**
