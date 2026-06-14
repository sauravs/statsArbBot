# Hyperliquid Integration — Research & Decision Record

**Date:** 2026-06-14
**Branch:** `hyperliquid`
**Status:** Decision finalised; implementation not yet started.
**Audience:** Future agents/operators picking up the second-exchange work.

This doc captures *why* we chose Hyperliquid and the venue-consistency reasoning
behind the backtest-data decision. For the file-by-file plan see
[`HYPERLIQUID_PLAN.md`](./HYPERLIQUID_PLAN.md); for live status see
[`HYPERLIQUID_PROGRESS.md`](./HYPERLIQUID_PROGRESS.md).

---

## 1. Decision summary

The bot currently integrates **dYdX v4** only. The next phase adds a **second
venue** for backtesting + manual/live trading.

**Decision:**
- **Phase 1 — integrate Hyperliquid for BOTH data and trading (venue-consistent).**
  Backtest on Hyperliquid's own price + funding data, execute on Hyperliquid.
- **Binance — deferred.** Kept as a *future, optional research/screening overlay*
  (long-history pair discovery), never as the decision-grade backtest source.
- **Full Binance *trading* integration — not planned** until there is a confirmed
  non-US, KYC-cleared deployment that needs its deeper exotic-pair liquidity.

---

## 2. Why Hyperliquid as the execution venue

| | **Hyperliquid** | **Binance Futures** |
|---|---|---|
| Type | Perp **DEX**, on-chain order book (HyperBFT) | **CEX** |
| Auth | **Wallet-based EIP-712 signing** (same paradigm as dYdX v4); agent/sub-wallets | API key + secret, HMAC-SHA256 |
| KYC | **None** (wallet-based) | Required for trading |
| US access | **No geo-block** | **Binance.com US-IP-blocked since 2019**; VPN use breaches ToS → account/fund-freeze risk |
| Python SDK | Official `hyperliquid-python-sdk` (v0.18.0+), EIP-712 handled, **testnet supported** | Mature (`binance-futures-connector-python` / `python-binance`), **testnet supported** |
| Order types | limit, market, stop, TP, trailing, reduce-only, TIF | Full suite |
| Perp universe | ~100+ curated; permissionless after HIP-3 (Oct 2025) | ~700 pairs (largest) |
| Liquidity | Deep on majors (BTC/ETH/SOL/top alts); large on-chain perp share by 2025 | Deepest overall, incl. exotics |

**Decisive factors for *this* bot:**
1. **Architectural reuse.** Hyperliquid mirrors dYdX v4 (DEX + EIP-712 wallet
   signing). Existing auth/signing/key-management patterns and "connect wallet"
   UX transfer directly. Binance forces a second, different auth paradigm (HMAC)
   and a CEX deposit/withdrawal model — more net-new surface.
2. **No KYC / no US geo-block.** Real-money mainnet is the eventual goal;
   Binance.com's US block + VPN-ToS risk is a legal/operational landmine for a
   money-handling bot.
3. **Production-ready trading stack.** Official SDK with a working testnet and
   EIP-712 abstracted away.

---

## 3. The backtest-data thesis: backtest on the venue you trade

Initial research leaned toward Binance for *data* (5+ yr clean OHLCV+funding
dumps via `data.binance.vision`, ~700 pairs) because Hyperliquid's live API caps
at **~5,000 candles** and the exchange is young (~2.5 yr). The operator
correctly challenged this as a **venue mismatch**. Conclusion: **for a stat-arb
bot the core backtest must be venue-consistent.**

Component-by-component:

- **Mid-price / spread signal — mismatch is harmless.** For liquid majors, perp
  mid-prices are tightly arbitraged across venues (track within bps), so the
  *cointegration relationship and z-score logic* are nearly identical on Binance
  vs Hyperliquid.
- **Funding — mismatch is disqualifying.** Funding rates are **venue-specific**
  (different markets, formulas, intervals) and are often the **dominant carry
  cost** for a market-neutral pairs position held across funding windows.
  Modeling Hyperliquid P&L with Binance funding systematically misstates returns.
- **Fills / slippage / fees / contract specs — venue-specific.** Book depth and
  fee schedules differ; realized entry/exit prices must come from the venue you
  actually trade.

**Therefore:** the go-live-gating backtest uses **Hyperliquid-native price +
funding data**. The ~5k-candle live-API cap is solved by pulling Hyperliquid's
**bulk S3 archive** (`s3://hyperliquid-archive/`, lz4, ~monthly) to build deep
history offline — so the data-depth argument for Binance largely dissolves.

**Binance's future role:** an *optional research/screening overlay* — use its
long history + large universe to *discover* candidate cointegrated pairs, then
**re-validate every candidate on Hyperliquid data** before it is tradeable.
Never let Binance numbers drive a go-live. The multi-exchange schema already in
place (`enum Exchange { dydx, binance, hyperliquid }`) makes adding this cheap later.

---

## 4. Data sources for Hyperliquid (implementation reference)

| Need | Source | Notes |
|---|---|---|
| Recent candles (live scan) | `info` → `candleSnapshot` | 1m–1M intervals; **~5,000-candle cap** regardless of `startTime` |
| Funding history | `info` → `fundingHistory` | start/end ms; **query in ~7-day windows** (long ranges truncate) |
| Deep historical backfill | **S3 archive** `s3://hyperliquid-archive/` | L2 + asset contexts, lz4, ~monthly; build candles from L2/trades. Third-party archives (Hydromancer, 0xArchive) can fill gaps |
| Trading + account | `hyperliquid-python-sdk` (v0.18.0+) | EIP-712 signing; **testnet** via configurable URL |

---

## 5. KYC / geo / legal notes (flag before mainnet)

- **Hyperliquid:** no KYC, wallet-based → low compliance friction. Operator must
  still independently assess DEX/perp regulatory exposure in their jurisdiction
  before mainnet real money. (Consistent with `CLAUDE.md`: going live is
  deliberate, never a deploy side effect.)
- **Binance (if ever revisited):** Binance.com blocks US IPs since 2019; VPN
  circumvention violates ToS (frozen accounts/funds). Binance.US is a separate,
  feature-restricted entity. Read-only public *data* (klines/funding) needs no
  KYC and is not geo-blocked.

---

## 6. Key sources

- Hyperliquid candle/funding endpoints & 5k cap: Hyperliquid docs (rate limits),
  Chainstack `candleSnapshot` / `fundingHistory`, ccxt issue #23243
- Hyperliquid S3 archive / bulk data: Hyperliquid historical-data docs,
  Hydromancer, 0xArchive
- SDK / EIP-712 / testnet: `hyperliquid-python-sdk` (DeepWiki), Chainstack
  user-signed actions; HIP-3 permissionless perps (Hyperdash)
- Binance klines/funding & bulk dumps: Binance derivatives REST docs,
  `binance/binance-public-data`, `data.binance.vision`
- Binance US restriction / VPN ToS risk: VPNOverview, Datawallet
