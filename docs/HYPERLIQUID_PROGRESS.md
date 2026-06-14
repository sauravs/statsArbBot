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
| 2 | Ingest: parameterise `make_fetch_client(exchange)`, `data/hyperliquid/`, refresh script | ⬜ |
| 2 | Registry: `integrated=True` (after backtest works) | ⬜ |
| 2 | Validate backtest on Hyperliquid data | ⬜ |
| 2 | `HyperliquidTradeClient` (TradeClient, testnet) | ⬜ |
| 2 | `make_trade_client()` venue dispatch + wallet config | ⬜ |
| 2 | Forward-test e2e on local dev stack | ⬜ |
| 3 | UI exchange selector (`ui/lib/api.ts` + components) | ⬜ |
| 4 | Tests + ADR-0011 + guide updates | ⬜ |

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

## Open questions / risks
- **Source/exchange decoupling:** `SCAN_DATA_SOURCE` conflates "data source"
  (fake vs live) with "which exchange". Decide whether to split cleanly now or
  extend the enum minimally. Plan §1/§3 leans toward decoupling.
- **S3 archive shape:** archive is L2/asset-contexts, not pre-baked OHLCV — must
  aggregate to candles. Confirm format + a backfill script before relying on it.
- **Funding windowing:** `fundingHistory` truncates long ranges — fetch in
  ~7-day windows.
- **SDK version:** pin `hyperliquid-python-sdk` (≥ v0.18.0) and confirm testnet URL.

## Next action
Plan **Phase 1, step 2–3**: extend `config.VALID_DATA_SOURCES` to include
`hyperliquid` (decide source/exchange decoupling) and teach
`make_data_client()` in `backend/exchanges/__init__.py` to dispatch by venue, then
parameterise `make_fetch_client(exchange)` in `ingest/historical_fetch.py`.
Note: `get_free_collateral`/account methods are deferred to Phase 2 (trade client,
needs wallet/`user_state`).

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
