# statsArbBot — User Guide

**For:** the trader operating the dashboard. Assumes you know pairs trading (cointegration, spread, z-score, hedge ratio); this guide explains how *this application* exposes those ideas and how to drive it day to day.

**Golden rule:** validate everything on **testnet** (and locally) before risking real funds. The app defaults to testnet on purpose.

---

## 0 · What this application does (in trading terms)

statsArbBot is a **statistical-arbitrage / pairs-trading** workbench for **dYdX v4 perpetual futures**. It:

1. **Scans** every eligible dYdX perp pair for **cointegration** (Engle-Granger), fits the **hedge ratio β** and intercept α, computes the **spread** `S1 − β·S2 − α` and its **Ornstein-Uhlenbeck half-life**, and keeps the pairs that are statistically sound *and* fast-reverting (`p < 0.05`, `0 < half-life ≤ 72h`).
2. Lets you **watch the spread's z-score** and act when it's abnormally wide.
3. Gives you **five ways to act on a signal**, from lowest to highest commitment:
   - **Manual trade** — you record a trade you take by hand (capital + P&L tracking), no orders placed.
   - **Real-time simulation** — paper trade on live prices.
   - **Fast-forward simulation** — replay history at speed to see how the strategy would have done.
   - **Walk-forward backtest** — rigorously evaluate strategies over sliding windows.
   - **Live bot** — the bot places real two-leg orders on dYdX (testnet or mainnet).

**The trading rules it enforces** (research-backed "Option-B" defaults — see `research.md`):

| Rule | Value | Meaning |
|---|---|---|
| **Entry** | `\|Z\| ≥ 1.5` | Spread is abnormally wide → open the pair. `Z<0` → **BUY base / SELL quote**; `Z>0` → **SELL base / BUY quote**. |
| **Exit (take-profit)** | `\|Z\| < 0.5` | Spread has reverted → close, take profit. (Tighter than zero-crossing to cut funding drag.) |
| **Stop-loss** | `\|Z\| ≥ 4.0` **or** age `> 3 × half-life` | Likely cointegration breakdown → cut losses. |
| **Sizing** | fixed notional per leg (default $100) | Market-neutral; quote leg scaled by β. |

---

## 1 · Run it locally first (recommended before any cloud deploy)

Testing on `localhost` (still reading dYdX **testnet/mainnet-prices**, placing no real orders unless you activate the live bot) catches bugs and answers UX questions with zero cloud cost. You need Docker.

```bash
git clone https://github.com/sauravs/statsArbBot.git && cd statsArbBot
cp .env.example .env          # set DASHBOARD_PASSWORD (your login passcode),
                               # POSTGRES_PASSWORD, DASHBOARD_JWT_SECRET; keep ENVIRONMENT=testnet
docker compose up -d --build   # builds + starts postgres + api + ui; migrations auto-apply
```

Open **http://localhost:3000**. To click around **without any network**, set `SCAN_DATA_SOURCE=fake` in `.env` (a deterministic demo dataset — great for learning the UI). Use `SCAN_DATA_SOURCE=dydx` for real pairs. When you're happy, deploy to AWS with `docs/AWS_DEPLOYMENT.md`.

> Stop with `docker compose down` (keeps your data) — `down -v` wipes the database.

---

## 2 · Logging in

The login screen shows **six passcode boxes**. Type your `DASHBOARD_PASSWORD` digit by digit (it auto-advances and auto-submits on the last digit; you can also paste). A wrong code **shakes** and clears. On success you land on the **Dashboard**.

> The passcode is the single shared secret — it also authorises the dashboard's calls to the backend. Treat it like a trading password.

---

## 3 · The dashboard at a glance

**Top header** (always visible):
- **📊 statsArbBot** title.
- **API** and **DB** status dots — green = healthy, yellow = checking, red = problem. If you see "Could not reach the API," the backend isn't up.
- Nav buttons: **Simulation · Fast-Forward · Backtest · Live Bot** (each opens a dedicated workspace) and **Log out**.

**Main body** (the home dashboard):
- **Cointegrated Pairs** panel — the scan controls, the z-threshold slider, and the pairs table. This is where you start.
- **Manual Trades** panel — your recorded manual trades and their P&L lifecycle.
- **Market data** control (in the controls row) — a **venue selector**: **Demo** (synthetic, offline), **dYdX**, or **Hyperliquid**. It sets the data source app-wide, so the scan, **Manual Trading**, and **Backtest** all operate on the venue you pick (badge shows `DEMO DATA` / `DYDX LIVE` / `HYPERLIQUID LIVE`). Switching clears the current pairs — re-scan after. *(Hyperliquid is enabled for Backtest + Manual Trading; its Live Bot / Simulation / Fast-Forward are not available yet.)*

---

## 4 · Finding pairs — the scan

In the **Cointegrated Pairs** panel:

- **Quick scan** — fewer history pages; fast, for a rough look.
- **Full scan** — full history; slower, the real result. A progress bar shows phase/percent; results persist (survive reload — they're in the DB).

When it finishes you get the **pairs table**, one row per surviving cointegrated pair:

| Column | What it tells you |
|---|---|
| **Pair** (base / quote) | The two markets. Click the row to open the **3-panel chart** (§6). |
| **Hedge β** | Units of quote per unit of base for a market-neutral position. |
| **Half-life (h)** | Hours for the spread to revert halfway. **Lower = faster = better** (capped at 72h). |
| **Z-score** | How many σ the spread is from its mean *right now*. The signal. |
| **p-value** | Cointegration significance (lower = stronger; all shown are < 0.05). |
| **Signal** | Derived from your slider threshold: **BUY base** (green, `Z ≤ −threshold`), **SELL base** (red, `Z ≥ +threshold`), or blank (no signal). |
| **Action** | A **Record** button — appears **only** on rows with an active signal. |

**How to read it as a trader:** prefer pairs with low p-value **and** short half-life (they revert fast enough to beat funding). A large `|Z|` on such a pair is your entry candidate.

---

## 5 · The Z-threshold slider & active signals

Above the table is a single-handle **Z-threshold slider** (range **0.5–4.0**, default **1.5**) drawn on a −5…+5 axis with a shaded neutral band between ∓threshold. Drag it and the table **re-filters live**: a pair becomes "active" (and reveals its **Record** button + a BUY/SELL **Signal**) when `|Z| ≥ your threshold`. Lower the slider to surface more (weaker) signals; raise it to see only the strongest dislocations.

---

## 6 · Studying a pair — the 3-panel chart

Click any pair row to open its detail view (`/dashboard/pair/<base>/<quote>`), three stacked, time-aligned charts:

1. **Normalized price overlay** — both legs rebased to 100, so you *see* them move together and diverge.
2. **Spread** — `S1 − β·S2 − α` with its **mean** line and **±1σ / ±2σ** bands (Bollinger-style). Wide excursions outside the bands are the opportunity.
3. **Z-score** — with horizontal lines at **±1.5** (entry) and **±4.0** (stop), plus **entry/exit markers**. This is the chart you trade off.

Use this to sanity-check a signal before acting: is the spread genuinely mean-reverting, or trending (cointegration breaking down)?

---

## 7 · Manual trading (record what you trade by hand)

The headline feature for a discretionary trader who places orders themselves but wants the system to **track and score** them.

The section applies p-value / half-life at **two layers** (#147, #150):

- **Filter (scan-time triage) — the control row under the header.** Set **max p-value** and **max half-life** (default 0.05 / 72h) to narrow the pairs table to those meeting your quality bar, using each pair's stats **from the last scan**. This is your selection aid — collapse 30+ pairs to the handful worth trading (e.g. tighten to p≤0.02, ≤24h). The header shows *"showing X of Y"* when a filter hides pairs; **reset** restores the defaults. These same values **pre-fill** the Record popup.
- **Gate (fresh re-validation) — at record time.** The authoritative check; see step 3. The triage filter is advisory (scan-time numbers); a recorded entry is *always* re-checked on fresh data, so a pair that looks fine in the table can still be blocked if it has decayed.

1. On an **active-signal** pair, click **Record**.
2. A popup asks for **capital for Leg 1 (base)** and **Leg 2 (quote)** in USD (defaults $100 each). It shows the pair's β, half-life, current z-score, spread and **p-value**. The system captures these plus the entry prices. An **Entry filters (advanced)** section lets you set a **max p-value** and **max half-life** (defaulting to the scan policy, 0.05 / 72h).
3. **Entry re-validation (#147).** On confirm, the system re-runs the cointegration + half-life test on **fresh candles** and **blocks the record (422)** if the pair now fails your thresholds — a scan is a point-in-time snapshot and cointegration can **decay** before you act, so this catches a pair that has gone stale (the same reason the backtest re-checks the filter every formation window). Tighten the thresholds for a higher-conviction entry. The p-value / half-life stored on the trade are these **fresh, re-validated** values.
4. Confirm → the trade appears in the **Manual Trades** panel as **OPEN**, with its **half-life** and **p-value** columns showing the *fresh, at-entry* values it was re-validated at (#153) — next to *Z @ entry*.
5. When you've closed the position on the exchange, click **Mark closed**, enter the **exit price for each leg**, and the system computes and stores **realised P&L** (per leg + total), flipping the trade to **CLOSED**.

This is order-execution-free: it's your journal + P&L engine for signals you act on manually. Direction is inferred from the entry z-score (the same rule the bot uses). See `docs/adr/0012-manual-entry-cointegration-revalidation.md` for why entry re-validates on fresh data.

---

## 8 · Live bot (real orders) — `Live Bot` nav

> ⚠️ Places **real orders** on dYdX. Use **forward_test (testnet)** until you've completed the pre-production checklist (`DEPLOYMENT.md` §7 / `AWS_DEPLOYMENT.md` §11).

The Live Bot workspace has:
- **Mode tabs:** `forward_test` (testnet) and `production` (mainnet).
- **Bot controls:** **Activate / Deactivate**, **Run entry scan** (with an optional entry-Z override), **Manage exits**, and **Abort all** (emergency flatten, behind a confirm).
- **Account card:** free collateral + equity.
- **Portfolio status:** open/closed/error counts + realised P&L.
- **Open Trades** table and **Trade History** (with exit reason + P&L).

**How it works:** entry and exit are **explicit passes** you trigger (or schedule via cron in production — see `AWS_DEPLOYMENT.md` §10). The bot places both legs **atomically**; if the second leg fails it immediately closes the first (failsafe), and if even that fails it raises a **CODE-RED** alert. A collateral guard blocks new entries when free collateral is low. Even when deactivated, you can still **Manage exits** / **Abort** so positions are always closable.

---

## 9 · Real-time simulation (paper trading) — `Simulation` nav

Create a session with starting capital; it **ticks on a schedule**, opening/closing **virtual** trades on real live signals using the *same* engine and rules as the live bot, with a realistic **cost model** (slippage, taker fee, funding). Controls: **create / pause / resume / stop / top-up capital**. Watch positions, P&L, and the equity curve update. The best way to build confidence in the strategy with no money at risk.

---

## 10 · Fast-forward simulation — `Fast-Forward` nav

Replays **historical** candles at N× speed through the same simulation engine over a date range you choose (leave dates blank in demo mode for the full history). When it finishes you get saved aggregates: an **equity curve**, **per-pair P&L**, and an **exit-reason breakdown**. Use it to ask "how would this have done last quarter?" in seconds. *(Needs the historical data seed — see `AWS_DEPLOYMENT.md` §12.)*

---

## 11 · Walk-forward backtest — `Backtest` nav

The rigorous evaluation: sliding **scan (90d) / trade (30d)** windows so pairs are re-selected out-of-sample, across strategies **S1–S4** (varying entry-Z and z-window). **Seed S1–S4** with one click, or **create** your own (name, capital, entry-Z, window lengths, date range). Run it; strategies are **ranked by net P&L**; each shows an **equity curve**, a **per-window** table, **per-pair P&L**, exit reasons, and a **markdown report**. Pause / stop / resume are supported. This is how you decide *which* parameters to trust before going live.

---

## 12 · Telegram (optional)

If configured (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`), the live bot can require a human **✅/❌ approval** in Telegram before every entry/exit (timeout auto-rejects — a safety default), and posts **CODE-RED** alerts. Commands: `/status`, `/balance`, `/positions`, `/pairs`, `/cancel`, `/activate`, `/deactivate`, `/help`. Leave it unconfigured and the bot auto-approves + logs instead (fine for testnet).

---

## 13 · A recommended workflow

A sensible path from idea to (eventually) live capital:

1. **Scan** (Full) → study the table; shortlist low-p-value, short-half-life pairs.
2. **Open the 3-panel chart** for each shortlisted pair — confirm clean mean reversion, not a breakdown.
3. **Backtest** S1–S4 (and your own variants) → see which parameters rank well; read the report.
4. **Fast-forward** your chosen settings over a recent period → sanity-check the equity curve.
5. **Real-time simulation** → paper-trade live for a while; confirm the sim matches your expectations.
6. Either **record manual trades** (you execute) **or** run the **live bot on testnet** (`forward_test`) and watch a full entry→exit cycle.
7. Only after the **pre-production checklist** (rotate secrets, validate a real testnet cycle, fix #16, enable Telegram approval) → switch a small allocation to **production**.

**What to watch:** half-life vs your holding tolerance, funding drag on slow pairs, p-value stability across scans, and — always — the stop-loss and abort controls.

---

## 14 · Glossary & deeper docs

- Domain terms (pair, leg, spread, hedge ratio, half-life, z-score, funding, CODE-RED): **`CONTEXT.md`**.
- Why the entry/exit/stop/half-life values are what they are: **`research.md`**.
- What the system does and its guarantees: **`PRD.md`**.
- Running it for real: **`AWS_DEPLOYMENT.md`** (cloud) / **`DEPLOYMENT.md`** (reference + non-Docker).

---

*Trade safe: testnet first, small size first, and never run mainnet on an unvalidated live order path (see the pre-production checklist).*
