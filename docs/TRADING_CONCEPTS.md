# Pairs Trading, in Plain English — Concepts, Math & How to Use This Bot

A field guide for the trading team. It builds intuition first (analogies, no math),
then the same ideas with numbers, then the parameter ranges people actually use,
then **exactly how to drive the Manual Trading and Backtest features in this
project**, and finally the tips & traps that separate "it ran" from "it's sound."

> Companion docs: `docs/BACKTEST_PARAMETER_GUIDE.md` (empirical presets that
> actually return pairs/trades here) and `docs/USER_GUIDE.md` (UI walkthrough).
> This file is the *why*; those are the *what to click*.

---

## Part 1 — The intuition (no math yet)

### The big idea: trade the *relationship*, not the *direction*
Most trading is a bet on direction: "BTC goes up." Pairs trading (a.k.a.
statistical arbitrage) bets on a **relationship between two assets snapping back to
normal** — and tries not to care whether the whole market goes up or down.

> **Analogy — two dogs on one leash.** A big dog (say SOL) and a small dog (say
> AVAX) are walked on a stretchy leash. They wander, but they can't drift too far
> apart — the leash pulls them back. Pairs trading ignores *where the dogs are
> going* and bets only on the **leash**: when the gap stretches unusually wide, you
> bet it'll close; when they're back together, you collect and reset. You don't
> care if the park is uphill (bull market) or downhill (bear) — only the gap.

That "gap" is the heart of everything below.

### Spread — "the gap between the dogs"
The **spread** is the distance between the two assets' prices, after scaling one so
they're comparable. When the spread is unusually wide, one asset is "too expensive"
relative to the other; you **short the expensive one and buy the cheap one**, and
wait for the gap to close.

### Correlation vs Cointegration — "walking together" vs "tied together"
- **Correlation** = "they tend to move the same direction *today*." Two random
  joggers heading north are correlated — but nothing stops them drifting miles
  apart forever.
- **Cointegration** = "they're **tethered** — the gap between them is stable over
  time and keeps returning to an average." *This* is what pairs trading needs.

> **Analogy — drunk and their dog.** A drunk staggering home (random walk) and
> their dog (also wandering) are *cointegrated*: the leash means the **distance**
> between them is predictable and mean-reverting, even though neither path is.
> Correlation is "they went the same way." Cointegration is "there's a leash."
> **You can only mean-revert a spread that is cointegrated.** Correlation alone
> will burn you — the gap can run away forever.

### Hedge ratio — "how much leash per dog"
Two assets rarely move 1-for-1. If SOL moves \$2 every time AVAX moves \$1, you must
hold **2 units of AVAX per 1 unit of SOL** to make the pair market-neutral. That
multiplier is the **hedge ratio** (β). Get it wrong and you're secretly betting on
direction, not the spread.

### Mean reversion & Half-life — "how strong, and how fast, the leash pulls"
- **Mean reversion** = the spread tends to return to its average.
- **Half-life** = **how long it takes the gap to close halfway**. Short half-life =
  a stiff, snappy leash (reverts in hours). Long half-life = a slack bungee
  (reverts in weeks — or maybe the leash is broken and it never comes back).

> **Analogy — a stretched spring.** Pull it and let go. Half-life is how quickly it
> springs back. A snappy spring (short half-life) is tradeable — you'll see the
> profit soon. A spring that takes a month is a capital trap: you're exposed to
> fees, funding, and "what if the relationship just *broke*?" the whole time.

### Z-score — "how weird is today, on a 1–10 weirdness scale"
The spread is wide… but *how* wide, in normal terms? The **z-score** answers
"how many standard deviations is today's gap from its recent average?"
- z ≈ 0 → totally normal (dogs together).
- z = +2 → unusually stretched **one way** (short the rich, buy the cheap).
- z = −2 → unusually stretched the **other way**.
- z = ±4 → *extreme* — either the chance of a lifetime, or the leash snapped.

> **Analogy — a fever thermometer for the pair.** 98.6°F is normal (z≈0). 101°F
> (z≈2) is "something's off, act." 104°F (z≈4) is "this may not be a fever at all —
> something's broken; get out." The z-score turns "the gap looks big" into a
> precise, comparable temperature.

### Z-window (lookback) — "what counts as *normal*"
A z-score needs a baseline: average and spread *over the last N bars*. That N is the
**Z-window**. Too short → jumpy, noise-driven signals. Too long → slow to notice a
genuinely new normal. (This bot defaults to **21** hourly bars.)

### p-value — "is this leash real, or did I get lucky?"
Before trusting a pair, you run a statistical test for cointegration. The
**p-value** is "the probability this 'relationship' is just random luck."
- p = 0.01 → only 1% chance it's a fluke → **strong** evidence of a real leash.
- p = 0.05 → standard academic cutoff ("probably real").
- p = 0.20 → weak; one in five such "pairs" is noise.

> **Analogy — "is this coin rigged?"** Flip 10 heads in a row and the p-value is
> tiny — almost certainly rigged (real signal). Flip 6 of 10 and the p-value is
> high — could easily be luck. The p-value cutoff is **how much coincidence you're
> willing to tolerate** before you call a pair "real."

### Entry / Exit / Stop — "the rules of the round trip"
- **Entry |Z|** — how stretched before you open (default **1.5**).
- **Exit |Z|** — how-back-to-normal before you take profit (default **0.5**).
- **Stop |Z|** — how extreme before you admit the leash broke and cut the loss
  (default **4.0**).
- **Time stop** — also bail if the trade just *sits* too long: this bot closes a
  position older than **3× the pair's half-life** (the spring should've sprung by
  now; if it hasn't, the thesis is stale).

The bot enforces the sane ordering **exit < entry < stop** — you profit inside the
band, you open at the edge, you bail beyond it.

### Walk-forward — "study last season, then play the next one — never peek"
To test a strategy honestly you split time into two moving windows:
- **Scan / formation window** — the *past* slice used to *find* cointegrated pairs
  and fit the hedge ratio ("study last season").
- **Trade / test window** — the *next, unseen* slice where you actually trade those
  pairs ("play this season").
Then you slide both forward and repeat. This prevents **look-ahead bias** — using
information you couldn't have known at the time, the #1 way backtests lie.

> **Analogy — closed-book exam.** Formation = studying the textbook. Trade window =
> the exam, where you *can't* see the answers. A strategy that only works when it
> peeks at the future is worthless live.

---

## Part 2 — The same ideas, with the math

Let two price series be `A` and `B` (we use **log prices** in practice).

**Spread** (hedge-ratio-adjusted):
```
spread_t = A_t − (α + β · B_t)
```
`β` (hedge ratio) and `α` (intercept) come from a regression of `A` on `B` over the
formation window. β tells you units of B per unit of A.

**Cointegration test (Engle–Granger):** regress `A` on `B`, then test whether the
residual (the spread) is **stationary** (mean-reverting) with an ADF test. Output =
**p-value**. Low p → stationary → tradeable leash. (We require `p ≤ PVALUE_MAX`.)

**Z-score** over the rolling Z-window (N bars):
```
z_t = (spread_t − mean(spread, N)) / std(spread, N)
```
Worked example: spread mean over last 21 bars = 0.00, std = 0.010, today's spread =
+0.022 → `z = 0.022 / 0.010 = 2.2`. That's past an entry of 1.5 → **open**:
short A, long β·B. When z falls back under 0.5 → **close** for profit.

**Half-life of mean reversion** (Ornstein–Uhlenbeck): fit
```
Δspread_t = λ · spread_(t−1) + ε      →      half_life = −ln(2) / λ
```
Example: λ = −0.04 per hour → `half_life = 0.693 / 0.04 ≈ 17h`. We reject pairs
slower than `MAX_HALF_LIFE_H` (default **72h**) — too slow to trade reliably.

**The round trip in numbers** (defaults): open at |z| ≥ **1.5**, take profit at
|z| ≤ **0.5**, hard-stop at |z| ≥ **4.0**, and time-stop after **3 × half-life**
hours regardless of z.

---

## Part 3 — Parameter ranges people actually use

General quant convention (and the bot's defaults / accepted ranges):

| Parameter | Typical range | This bot default | Accepted range |
|---|---|---|---|
| Entry \|Z\| | 1.5–2.0 (1.0 = trade more, noisier) | **1.5** | 0.5–4.0 |
| Exit \|Z\| | 0.0–0.5 | **0.5** | >0–2.0 |
| Stop \|Z\| | 3.0–4.0 | **4.0** | 1.0–10.0 |
| Z-window | 20–60 bars | **21** | — |
| p-value | 0.05 standard | **0.05** | tighter = stricter |
| Half-life | ≤72h (crypto: looser) | **72h** | — |
| Scan/formation | 60–120d clean data | — | — |
| Trade/test | 30–180d | — | — |

**Reading these as a trio:** lower entry + lower p-value tolerance + shorter
half-life = *fewer, higher-quality* trades. Higher entry catches only big
dislocations (rarer, often higher win-rate). It's a dial between **frequency** and
**conviction**.

---

## Part 4 — How to use *our* features

### ⚠️ Read this first: DEMO vs LIVE data (the #1 gotcha)
The Backtest/Manual pages have a **DEMO / LIVE** badge driven by `SCAN_DATA_SOURCE`:
- **LIVE (`dydx`)** — real dYdX market history (the production server runs this;
  cache currently holds ~43 markets, 2024→2026).
- **DEMO (`fake`)** — a synthetic dataset with a couple of *by-construction*
  cointegrated pairs. Great for learning the UI; **not real markets**.

**Always check the badge before trusting a result.** "0 pairs / 0 trades" is almost
always a data-source/date-range mismatch, not a broken strategy — see
`docs/BACKTEST_PARAMETER_GUIDE.md`.

### Backtesting — recommended workflow
1. **Confirm the badge** (LIVE for real research).
2. **Start from a known-good preset**, then change *one thing at a time*:
   - **LIVE / real data:** Entry 1.0–1.5, Exit 0.5, Stop 4, **p ≤ 0.10**,
     **half-life ≤ 168h**, Z-window 21, **scan 30d / trade 15d**, dates in a
     *dense* span (e.g. 2024-02 → 2024-12). Real crypto cointegration is rare and
     completeness thins the universe, so these looser values are what *return*
     pairs at all.
   - **DEMO:** Entry 1.5, Exit 0.5, Stop 4, p ≤ 0.05, half-life ≤ 72h — normal
     values "just work" because the demo pairs are clean.
3. **Read the right metrics, in order:** pairs found → trades → **win %** and **net
   P&L** → the **equity curve shape** (smooth and up-and-to-the-right beats a
   jagged line that happens to end positive) → exit-reason mix (are profits from
   real reversion, or are stops/time-stops dominating?).
4. **Walk-forward, don't single-shot.** A result from one window is an anecdote;
   consistency across sliding windows is evidence.

### Manual Trading — recommended approach
1. Use the **scan** to surface current cointegrated pairs; sort by p-value and
   half-life — **prefer low p (real) and short half-life (snappy)**.
2. Open the **pair detail** and look at the spread/z chart: you want a spread that
   visibly oscillates around a flat mean, *currently* stretched toward your entry —
   not one that's trending (a broken leash).
3. Enter near your entry |Z|, pre-decide your exit and stop **before** you click,
   and size so **both legs are market-neutral** (respect the hedge ratio).
4. Let the exit/stop/time-stop rules do their job — **don't "give it more room."**
   A blown stop usually means the cointegration broke, exactly when discipline
   matters most.

---

## Part 5 — Perpetual-futures mechanics & the real costs

Pairs trading here happens on dYdX **perpetual futures** ("perps"), not spot. Perps
add mechanics that hit P&L directly — above all **funding**. These are often what
turns a "profitable" spread backtest into a losing live trade.

### Perpetual futures & the funding rate — "rent that pulls prices home"
A perp never expires, so an anchor keeps its price near the underlying **spot**
price: the **funding rate**, a small payment exchanged **between longs and shorts**
(on dYdX, **hourly**).
- Perp **above** spot (premium) → **positive** funding → **longs pay shorts**.
- Perp **below** spot (discount) → **negative** funding → **shorts pay longs**.

> **Analogy — rent on a crowded side.** When everyone crowds the long side
> (bullish), being long charges *rent* (you pay funding); that rent nudges traders
> to trim longs / add shorts, dragging the perp back toward spot. Funding tethers
> perp→spot, much like cointegration tethers asset→asset.

Math: hourly funding P&L ≈ `funding_rate × position_notional`. A `0.01%/hr` rate on
a \$10k position = \$1/hr ≈ **\$24/day** — paid or received *every hour you hold*.

### Funding inside a *pair* — it cuts both ways
A market-neutral pair is **long one leg, short the other**, so you sit on **both**
sides of funding at once:
```
net funding per hour ≈ (funding_rate_short_leg − funding_rate_long_leg) × notional
```
You **receive** funding on the short leg (when its funding is positive) and **pay**
on the long leg. So a pair can **earn carry** or **bleed it**. Over a multi-day hold
(long half-life!), **funding can dwarf the spread profit** — which is exactly why
the bot caches funding history and why the half-life cap matters: *the longer you
hold, the more funding, not the spread, decides your P&L.*

### Liquidity, depth & slippage — "how big a splash you make"
**Liquidity** = how much you can trade without moving the price. The order book has
**depth** at each level; a market order eats through it and fills at progressively
worse prices = **slippage**.

> **Analogy — pond vs ocean.** Drop a rock (your order) in a small pond (thin
> market) → big splash (price moves against you). Same rock in the ocean (deep
> market) → barely a ripple. What matters is **your size relative to the depth.**

In this bot: the live path places **market orders with a 5% price buffer**
(`ORDER_PRICE_BUFFER`) and short-lived orders to ensure fills — but **backtests
assume clean fills**, so live results are typically *worse* than backtests,
especially on thin pairs. Always discount a backtest for real slippage.

### Volume & open interest — "traffic flow vs cars parked"
- **Volume** = amount traded over a period (the *flow*). Higher volume → tighter
  bid/ask, easier fills, more trustworthy prices.
- **Open interest (OI)** = contracts currently open (the *stock* of positions).
  Large, lopsided OI → bigger funding swings.
- The scan filters illiquid markets via `MIN_LIQUIDITY_USD` (**\$1M** 24h volume,
  Phase-2 default; was \$10k), because thin markets have wide spreads, **gappy
  candles** (which break the cointegration alignment and drop the market from the
  scan), and erratic funding. The \$1M floor is for *tractability* — a fillable,
  reviewable shortlist — not for edge (see `docs/PHASE2_STRATEGY_PLAN.md` §5).

**How they interrelate:** high volume + deep liquidity → low slippage, stable basis,
modest funding. Thin/low-volume → high slippage, jumpy basis, volatile funding, and
missing bars that disqualify the market entirely. So liquidity quietly governs
*both* your execution cost *and* whether a pair even qualifies to trade.

### Leverage, margin & liquidation — "the amplifier with a tripwire"
Perps let a small **collateral** (margin) control a large notional = **leverage**.
It scales P&L *and* risk: move far enough against the position and you hit
**liquidation** (a forced close at a loss). Even a market-neutral pair has
leg-level liquidation risk if one side gaps. Keep leverage modest and respect the
account's minimum-collateral setting (`USD_MIN_COLLATERAL`).

### Sizing the legs — dollar-neutral vs beta-neutral
- **Dollar-neutral:** equal \$ long and short (e.g. \$5k each). Simple — but if one
  leg is twice as volatile, you're secretly net-long/short the market.
- **Beta-neutral:** size by the **hedge ratio (β)** from the cointegration fit so
  your exposure is the *spread itself*, not market direction. **This is the correct
  way** to make a pair genuinely market-neutral.

### Fees & basis — the smaller, constant drains
- **Fees:** every entry *and* exit pays a taker fee; round-trips compound, and
  high-frequency / low-edge configs (low entry |Z|) bleed the most. Sanity check:
  does the average winning trade clear the **round-trip cost** (fees + slippage +
  funding)?
- **Basis** = perp − spot. It wobbles with leverage demand; a large/erratic basis
  signals stressed conditions where a "clean" spread is anything but.

---

## Part 6 — Tips, caveats & hard-won lessons

- **Finding trades ≠ making money.** On real crypto perps, naive cointegration
  pairs are typically **net-negative after fees + funding** (documented in our own
  sweeps). Getting pairs/trades is solved; *profitability* is a separate problem of
  pair selection, costs, and sizing. Treat green backtests with suspicion until
  they survive costs and walk-forward.
- **Crypto has one giant factor: BTC.** Most coins move with Bitcoin, so genuine
  *pairwise* cointegration (beyond "both follow BTC") is scarce and **unstable** —
  a pair cointegrated last quarter often isn't next quarter. Re-test, don't marry.
- **Overfitting is the cardinal sin.** If you tune 8 knobs until one historical
  window prints profit, you've curve-fit noise. Prefer *fewer* parameters,
  *rounder* numbers, and results that hold across windows.
- **Look-ahead bias hides everywhere.** Only ever form pairs on the formation
  window and trade them on the *later* window. Our walk-forward enforces this — use
  it; don't eyeball the whole history and "pick the good pairs."
- **Data completeness silently shrinks your universe.** The scan drops a market
  missing even one bar in a window, so longer windows = fewer aligned markets.
  Shorter scan windows and denser (earlier) spans surface more candidates.
- **Costs are the real opponent.** Fees + funding + slippage are paid *every* round
  trip. High-frequency low-edge configs (low entry Z) bleed the most. Always
  sanity-check: does the average winning trade clear the round-trip cost?
- **Half-life is your patience budget.** A pair with a 200h half-life ties up
  capital and risk for days per trade. The 72h cap exists for a reason.
- **Liquidity matters.** Thin markets gap and slip; respect `MIN_LIQUIDITY_USD`
  (\$1M default; was \$10k) and remember backtests assume fills you may not get live.
- **DEMO is for learning, not for decisions.** Profitable DEMO numbers say the
  *plumbing* works, nothing about real edge. Validate on LIVE.
- **Start small and staged when going live.** (Live trading is a separate, gated
  step — see `docs/DEPLOYMENT.md` §7. Don't skip testnet validation.)

---

### One-line mental model
> Find two assets tied by a real, statistically-verified leash (**low p**), that
> snaps back quickly (**short half-life**); wait until the gap is unusually wide
> (**high |z|**); bet on the snap-back; take profit when it's normal again
> (**low |z|**); and cut it if the leash breaks (**stop**) or the snap never comes
> (**time-stop**) — all tested **out-of-sample** (**walk-forward**), after costs.

---

## Part 7 — FAQ: straight answers to questions the desk actually asked

Real questions from the team, answered in the same plain English as the rest of this
guide. (If you ask a new one, it gets logged and may land here.)

### "Quick scan vs Full scan — what's the difference, and which do I trust?"
Both do the **same job**: sweep every eligible dYdX perp pair, test for cointegration,
fit the leash (**β / α**), and keep the pairs that are statistically real *and* snap back
fast (`p < 0.05`, half-life ≤ 72h). The only difference is **how much history they read**:

| | History | ≈ Span (1h candles) | Use it for |
|---|---|---|---|
| **Quick scan** | 2 pages | ~200h ≈ **8 days** | A fast first look |
| **Full scan** | 4 pages | ~400h ≈ **16–17 days** | The real result (saved to the DB, survives reload) |

> **Analogy — the route preview.** Quick scan is the **instant ETA** your maps app shows
> the second you type a destination — good enough to decide if the trip is worth it. Full
> scan is the route **after it pulls live traffic**: slower, but the one you actually
> drive. A pair that looks tied together over 8 days can fall apart over 16 — so **scan
> Quick to browse, Full before you risk anything.**

### "Why does it say BUY base / SELL quote here, but the opposite there?"
Because the **sign of the z-score** sets the direction, and the trade always bets the gap
**closes** (mean reversion). Back to the leash:

- **`Z < 0`** — the spread is unusually *low*: the **base dog lagged behind**. Bet it
  catches up → **BUY base, SELL quote.**
- **`Z > 0`** — the spread is unusually *high*: the **base dog ran ahead**. Bet it falls
  back → **SELL base, BUY quote.**

You're never betting on either coin's *direction* — only on the **leash pulling them level
again**. That's why both legs go on at once and the quote leg is scaled by **β** (so a
market-wide move roughly cancels out). The app reads the entry z-score and labels the
direction for you — the same rule the live bot uses.

> **Worked example.** `SOL/ETH`, β = 2. Spread hits **Z = −2.1** (past the 1.5 entry) → Z
> is negative → **BUY ~$100 of SOL / SELL ~$200 of ETH**. It reverts to **Z = −0.3**
> (inside the 0.5 exit) → close both legs, pocket the snap-back. Negative-Z set the whole
> direction.

### "What's the Z-threshold slider actually for?"
It's your **sensitivity dial** for what counts as a tradable signal. A pair only lights up
(shows a BUY/SELL signal and a **Record** button) when **`|Z| ≥ your threshold`**. Slide it
**down** (toward 0.5) to surface more — and weaker — signals; slide it **up** (toward 4.0)
to see only the most extreme, high-conviction dislocations. The table re-filters live.

> **Analogy — the metal-detector knob.** Turn sensitivity **up** and it only beeps for big,
> deep targets (few false alarms, but you miss small finds). Turn it **down** and it beeps
> at every bottle cap (you see everything, mostly noise). **1.5 is the researched sweet
> spot** — wide enough to be a real dislocation, tight enough that you still trade.

> ⚠️ The slider only changes **what you see**. The bot's safety rails are fixed regardless:
> **take-profit at `|Z| < 0.5`** and **stop-loss at `|Z| ≥ 4.0`** (or age > 3 × half-life).

### "On the pair chart — what is 'Normalized price (rebased to 100)'?"
The top panel of the 3-chart pair view rescales **each leg so its first bar in the window
= 100**, then plots everything relative to that (`price ÷ first price × 100`). So **112
means "up 12% since the window started"**; **95 means "down 5%."**

> **Why bother.** The two legs trade at wildly different prices — BTC near $60,000, SOL
> near $150. On a raw axis the cheap one is a flat line on the floor and the expensive one
> dominates; you simply can't *see* them move together. Rebasing both to 100 puts them on
> the same percentage ruler, so the **co-move — and the divergence — jump out at a glance.**
> It's the human-eye version of the spread and z-score panels below it.

**One caveat:** that overlay is **diagnostic only** — it doesn't generate signals. The
trade fires off the **spread** and the **z-score** (the bottom panel, the one you actually
trade). The rebased-to-100 line just makes the leash *visible*.

### "What's the 'Z thresholds · entry / exit / stop · Edit' badge — and what changes if I edit it?"
That badge shows the **strategy's actual signal rules** — the entry, exit and stop **|Z|**
levels (the "rules of the round trip" from Part 1). Hit **Edit**, change the numbers, and
**Apply** and they update **everywhere at once, instantly** (no restart), and are **saved** so
they survive a reboot. (It enforces `exit < entry < stop`, so you can't set nonsensical rules.)

**What moves when you change it:**
- The **entry / exit / stop reference lines** — and the entry/exit markers — on **every pair's
  Z-score chart**, redrawn to your new levels the next time you open a pair.
- The **default rules the live bot and the simulations** (real-time + fast-forward) trade by.

**What it deliberately does *not* touch:**
- It is **not** the **"Active when |Z| ≥ threshold" slider** beside the pairs table. That slider
  is only a *view filter* — it decides which pairs are highlighted and get a **Record** button,
  and it lives **only in your browser**. Editing the strategy thresholds won't add or remove
  Record buttons.
- It **doesn't rewrite trades you've already recorded** — a manual trade snapshots its numbers
  at the moment you record it.
- It **triggers no automatic action** — manual trades have no auto-exit; you still close them
  yourself with **Mark closed**.

> **Rule of thumb — two Z controls, two jobs.** The **[Edit] badge** is the *real* strategy
> entry/exit/stop: global, saved, and what the bot and charts actually use. The **slider** is a
> *throwaway lens* for browsing the table. Edit the badge to **retune the strategy**; nudge the
> slider just to **see more or fewer candidates.**
