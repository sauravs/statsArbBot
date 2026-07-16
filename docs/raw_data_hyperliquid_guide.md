# Raw Hyperliquid OHLCV Data — Guide

This guide documents the per-market Hyperliquid data files in this bundle
(`hl_ohlcv_csv_xlsx/`) — what each column means, where the numbers come from, and
**exactly how the bot cleans, filters, aligns, and smooths this data in later steps**.

> TL;DR for the downstream pipeline: of the seven columns, **only `close` is used
> in the statistical math.** `open/high/low` and `volume` are used *only* to reject
> bad bars at ingest and to gate which markets are eligible — never inside the
> cointegration / z-score calculations. There is **no log-price transform**; the
> regression runs on raw price *levels*.

---

## 1. What's in this bundle

- **180 markets**, one pair of files per market: `BTC.csv` + `BTC.xlsx`, `ETH.csv` + `ETH.xlsx`, …
- **Resolution:** hourly bars (`1HOUR`), one row per market per hour.
- **Coverage:** 2024-01-01 00:00 UTC → 2026-07-11 03:00 UTC.
- **Exchange:** Hyperliquid perps (keyed by coin symbol, e.g. `BTC`, not `BTC-USD`).
- CSV and XLSX hold identical data; the XLSX stores OHLCV as real numbers so Excel
  formulas / pivots work directly.

---

## 2. File / sheet structure — the 7 columns

Each file/sheet has **7 columns**:

| # | Column      | Type              | Unit / format                         | Meaning |
|---|-------------|-------------------|---------------------------------------|---------|
| 1 | `market`    | text              | coin symbol (`BTC`, `ETH`, `kPEPE`…)  | Which market the row belongs to. Redundant within a per-market file, kept so the schema matches the combined export. |
| 2 | `timestamp` | datetime (UTC)    | `YYYY-MM-DD HH:00:00+00`              | Bar open time, top of the hour, timezone-aware UTC. |
| 3 | `open`      | number            | USD price                             | First price in the hour. |
| 4 | `high`      | number            | USD price                             | Highest price in the hour. |
| 5 | `low`       | number            | USD price                             | Lowest price in the hour. |
| 6 | `close`     | number            | USD price                             | Last price in the hour. **This is the only column used downstream.** |
| 7 | `volume`    | number            | USD notional (see §3 caveat)          | Liquidity proxy — semantics differ by era (read §3). |

Rows are **sorted ascending by timestamp** within each market, de-duplicated on
timestamp, and cleaned (see §4).

---

## 3. Where the numbers come from (provenance & caveats)

Hyperliquid's public candle API only serves a rolling ~5,000-bar (~208-day)
window, so history older than ~7 months **cannot** come from the live API. This
dataset is stitched from two sources, and the semantics of `open/high/low/close`
and especially `volume` **differ by era** — important for your analysis:

| Era (approx.) | Source | Prices (OHLC) | `volume` column |
|---|---|---|---|
| **2024-01-01 → ~2025-12-04** | Hyperliquid **S3 archive** (`asset_ctxs`), via `ops/hl_deep_backfill.py` | **Mid-price** based: minute `mid_px` aggregated into hourly OHLC (open = first minute, close = last minute, high/low = min/max) | **24-hour rolling notional proxy** (`day_ntl_vlm`) — **NOT** per-bar volume |
| **~2025-12-05 → present** | Live `/info candleSnapshot` (via `POST /api/data/fetch` + daily `topup.sh`) | **Trade-based** candles from the exchange | **Per-bar base-token volume** (`v`) |

Consequences for analysis:

- **OHLC:** the deep-history portion is *mid-price* (not trade-price) OHLC.
  Validation on 2026-07-02 showed archive closes track live trade-based closes
  within **~0.03–0.05%** (BTC/ETH/SOL) — negligible for close-price / cointegration
  work, but be aware `high`/`low` are mid-based extremes, not trade extremes.
- **`volume` is NOT consistent across the full history** and mixes two different
  definitions at the ~Dec-2025 seam. Treat it as a coarse liquidity signal only.
  (The bot itself never uses this per-bar `volume` in price math — see §5.2.)

---

## 4. How the raw bars are CLEANED at ingest

Before any bar is stored, it passes through `clean_ohlcv()`
(`backend/ingest/cleaning.py:106-180`). Type coercion first
(`_coerce`, lines 73-79): `timestamp → UTC datetime`, OHLCV → numeric; unparseable
values become NaN. Then rows are dropped by these rules **in this exact priority
order** (so the drop counts are disjoint and reconcile to the raw total):

1. **Unparseable** — any required field NaN after coercion (lines 128-131).
2. **Duplicate timestamps** — stable-sort by timestamp, keep the **last**
   occurrence of each (lines 133-137).
3. **Non-positive prices** — drop if any of O/H/L/C ≤ 0 (lines 139-142).
4. **OHLC inconsistency** — drop if `high < low`, or if high/low don't bracket
   open and close (lines 144-149).
5. **Zero/negative volume** — drop `volume <= 0` (config `INGEST_DROP_ZERO_VOLUME`,
   default `True`; lines 151-156). Rationale: no-trade hours get forward-filled and
   pin the spread artificially.
6. **Flat bars** — drop `high == low` (zero intra-bar range, the forward-fill
   artefact; config `INGEST_DROP_FLAT`, default `True`; lines 158-163).

Two things the cleaner deliberately does **NOT** do:

- **No gap-filling / resampling at ingest.** Missing hours are *detected and
  reported* (`detect_gaps`, lines 82-103) but never fabricated. So a per-market
  file can have hour gaps — do not assume a perfectly contiguous hourly grid.
- **No smoothing / outlier clipping** at this stage.

Coverage gate (batch path): a market needs ≥ `INGEST_MIN_COVERAGE_ROWS` (2160 =
90 days of hours) of clean rows or it's excluded (`pipeline.py:136`).

---

## 5. How the CLEANED data is USED downstream (filter → align → smooth → signal)

The full data flow:

```
raw candle
  → clean_ohlcv (dedup / drop bad+flat+zero-vol / sort)         [ingest/cleaning.py]
  → ohlcv_cache (Postgres)                                       [ingest/cache_repository.py]
  → get_candles → {timestamp, close} only, ascending            [ingest/cache_repository.py:228]
  → price matrix: align many markets on shared timestamps        [marketdata/price_matrix.py]
  → analyze_pair: Engle-Granger + OLS hedge ratio β, intercept α [statcore/cointegration.py]
  → spread = S1 − β·S2 − α                                        [statcore/spread.py]
  → rolling z-score (window = 21)                                [statcore/zscore.py]
  → entry / exit / stop signal                                   [statcore/signals.py]
```

### 5.1 Only `close` is read
`get_candles()` returns **only** `{timestamp, close}` per bar, ascending
(`cache_repository.py:228-256`). `open/high/low/volume` never reach the analysis
layer.

### 5.2 Market eligibility FILTERS (which coins even qualify)
Applied in the exchange client `get_markets()`
(`exchanges/hyperliquid/client.py:220-264`):
- **Delisted** markets dropped (`isDelisted`).
- **Stablecoins** dropped — substring match against `STABLECOIN_KEYWORDS`
  (USDC/USDT/DAI/BUSD/TUSD/FRAX/LUSD/USDD/USDP/PYUSD).
- **Liquidity gate:** drop if 24h notional `dayNtlVlm < MIN_LIQUIDITY_USD`
  (default **$10,000**). *(This is the same 24h-notional family as the deep-history
  `volume` column, but it's read live from `metaAndAssetCtxs`, not from the bar.)*
- **Min history:** a market needs ≥ `MIN_CANDLES_PER_MARKET` (50) closes or it's
  dropped as `too_short` (`price_matrix.py:148`).

### 5.3 ALIGNMENT (turning many 1-column series into one matrix)
- **Live scan** (`price_matrix.py:81-189`): build a DataFrame (columns = markets,
  index = timestamp), then **inner join** via `df.dropna(axis=1, how="any")`
  (line 167) — any market missing *any* shared timestamp is dropped (`misaligned`).
  Strict: no forward-fill in the live scan.
- **Backtest** (`backtest/scan_window.py:28-86`): more tolerant — keep a market if
  it has ≥ `BACKTEST_MIN_COMPLETENESS` (**0.90**) of the window's bars, then
  `ffill().bfill()` to fill small residual gaps (line 84). Never mean/median-fill
  (prices are non-stationary).

### 5.4 The statistics (no smoothing of prices themselves)
Per pair `(S1, S2)` of **raw close levels** — no log transform
(`statcore/cointegration.py:134-178`):
1. **Engle-Granger cointegration test** (`statsmodels.coint`) → `p_value`,
   `t_statistic`, `critical_value_5pct`. Pair is "cointegrated" if
   `p_value < PVALUE_MAX` (0.05) **and** `t_statistic < critical_value_5pct`.
2. **Hedge ratio via OLS** `S1 = α + β·S2 + ε` → `β` (hedge_ratio), `α` (intercept).
3. **Spread** `= S1 − β·S2 − α` (`spread.py:22-45`) — centred on zero.
4. **Half-life** (Ornstein-Uhlenbeck): regress `Δspread_t = a + b·spread_{t-1}`,
   `half_life = −ln(2)/b` (`halflife.py`). Rejected if not mean-reverting or if
   `half_life > MAX_HALF_LIFE_H` (72h).
5. **Zero-crossings** counted as a mean-reversion quality metric.

### 5.5 SMOOTHING — the rolling z-score
This is the only "smoothing" step, and it's applied to the **spread**, not to the
raw prices (`statcore/zscore.py:23-58`):

```
z_t = (spread_t − rolling_mean(spread, window)_t) / rolling_std(spread, window)_t
```

- `window = ZSCORE_WINDOW` (**21** hours). Rolling std is sample (ddof=1).
- The first `window-1` values are NaN; a signal needs a full window of data
  (`min_rows = ZSCORE_WINDOW + 10` bars per pair, `scan/orchestrator.py:205`).
- **No winsorization / outlier clipping** anywhere — the drop-flat / drop-zero-vol
  rules at ingest are the only outlier defense.

### 5.6 Signals (how z-score filters to actions)
`statcore/signals.py`:
- **Entry** when `|Z| ≥ ZSCORE_THRESH` (**1.5**). `Z<0` → BUY base / SELL quote;
  `Z>0` → the reverse.
- **Exit** precedence: (1) stop-loss `|Z| ≥ STOP_LOSS_ZSCORE` (**4.0**),
  (2) take-profit `|Z| < EXIT_ZSCORE` (**0.5**), (3) time-stop when position age
  `> TIME_STOP_HALF_LIFE_MULT` (**3.0**) × half-life.

---

## 6. Config reference (the knobs that govern cleaning/filtering/smoothing)

All in `backend/config.py`:

| Parameter | Default | Role |
|---|---|---|
| `CANDLE_RESOLUTION` | `1HOUR` | Bar size. |
| `INGEST_DROP_FLAT` | `True` | Drop `high==low` bars at ingest. |
| `INGEST_DROP_ZERO_VOLUME` | `True` | Drop `volume<=0` bars at ingest. |
| `INGEST_MIN_COVERAGE_ROWS` | `2160` | Min clean rows (90d) for a market (batch path). |
| `MIN_LIQUIDITY_USD` | `10000` | 24h-notional liquidity gate. |
| `STABLECOIN_KEYWORDS` | USDC,USDT,… | Excluded symbols. |
| `MIN_CANDLES_PER_MARKET` | `50` | Min closes to enter the price matrix. |
| `BACKTEST_MIN_COMPLETENESS` | `0.90` | Min window coverage before ffill/bfill (backtest). |
| `ZSCORE_WINDOW` | `21` | Rolling mean/std window for the z-score. |
| `ZSCORE_THRESH` | `1.5` | Entry threshold on `|Z|`. |
| `EXIT_ZSCORE` | `0.5` | Take-profit threshold. |
| `STOP_LOSS_ZSCORE` | `4.0` | Stop-loss threshold. |
| `PVALUE_MAX` | `0.05` | Cointegration p-value cutoff. |
| `MAX_HALF_LIFE_H` | `72` | Max acceptable half-life (hours). |
| `TIME_STOP_HALF_LIFE_MULT` | `3.0` | Time-stop = this × half-life. |

---

## 7. Reproducing the cleaning yourself (Excel / pandas)

If you want to mirror what the bot does to these files before analysis:

1. **Per market**, drop rows where any of O/H/L/C is blank, ≤ 0, or `high < low`,
   or high/low don't bracket open/close.
2. Drop **flat** bars (`high == low`) and **zero-volume** bars.
3. **Sort by `timestamp`**, drop duplicate timestamps (keep last).
4. Keep only the `close` column for pair analysis.
5. **Align two markets** by inner-joining on `timestamp` (Excel: `XLOOKUP`/Power
   Query merge; pandas: `df1.join(df2, how="inner")`). Require enough overlapping
   bars (the bot needs ≥ 31 for a z-score signal, ≥ 50 to consider a market).
6. Fit `S1 = α + β·S2`, form `spread = S1 − β·S2 − α`, then a **21-period rolling
   z-score** of the spread. Signal when `|z| ≥ 1.5`.

> Note: the bot does **not** log-transform prices and does **not** smooth raw
> prices — the only smoothing is the 21-hour rolling mean/std inside the z-score.

---

## 8. Gotchas checklist

- ✅ Use **`close`** for analysis; `open/high/low` are QC-only, `volume` is a coarse
  proxy with **mixed definitions across the Dec-2025 seam**.
- ✅ Hours can be **missing** (gaps are not filled in the export) — align on
  timestamp, don't assume a contiguous grid.
- ✅ Deep-history OHLC is **mid-price** (~0.05% off live) — fine for close-price
  work, not for microstructure.
- ✅ Timestamps are **UTC**, hour-aligned.
- ✅ Not every market spans the full range — many perps listed after 2024-01-01, so
  their files start later.
