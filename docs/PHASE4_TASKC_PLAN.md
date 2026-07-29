# Phase 4 — Task C: edge-hunt campaign plan (grid proposal, pre-approval)

**Status:** PROPOSAL for operator approval. **No strategy rows created, no prod action taken.**
**Date:** 2026-07-29
**Gate:** `.claude/CLAUDE.md` + `docs/PHASE2_STRATEGY_PLAN.md` §1 (B1–B5). Approval of the grid
below is required *before* any campaign is created; launching it on prod is a **separate**
explicit approval.

> **Standing verdict is unchanged and is not up for revision here: NO-GO.** This is an honest
> search, not a mandate to find a yes. `ENVIRONMENT` stays testnet. Nothing in this plan ships a
> live strategy or relaxes a gate.

---

## 0. TL;DR — what to test, and what I expect it to show

**Proposed experiment:** the **entry-threshold × per-leg-size interaction**, out-of-sample, with
honest costs on.

**Why this and not another parameter sweep:** every lever has already been swept *at one size*
($100/leg) and the complete lever taxonomy says none creates an OOS edge (`docs/strategy.md`,
2026-07-21). But **size was never crossed with anything.** Phase-2 measured exactly two points on
that surface — (entry 3.5, $100) and (entry 3.5, $1,000) — and phase-1 could not have explored it
at all, because phase-1 never charged market impact. The interaction is the one region where
phase-2's *own mechanism* predicts the ranking could invert (§2). That is a new angle, not a tweak.

**My honest prior: it will still fail.** §3 extrapolates the documented numbers and lands at
roughly break-even *at best*, comfortably short of the +$424 bar. I am proposing it anyway because
it is the last cheap, well-motivated question on the current signal, and settling it with real
measurement is worth more than settling it with my arithmetic. **If the operator wants to skip it
on that basis, that is a reasonable call** — §6 gives the alternative.

---

## 1. What phase-1 and phase-2 already covered

**Phase-1 (ad-hoc, ~69 configs, all at $100/leg, old flat cost model).** Every axis, exhausted:

| Lever | Verdict (`docs/strategy.md`) |
|---|---|
| Exit \|Z\| | noise — no OOS edge |
| Entry \|Z\| | the dominant lever; single-peaked at 3.5; still OOS-negative at every value |
| p-value | potent below 0.05, then saturates — prevents ruin, not loss |
| Half-life cap | **non-binding / inert** — a 24h cap removes only ~4% of trades |
| Stop \|Z\| | pure risk/return trade-off — tilts, never lifts |
| Scan/trade windows | swept (the `window-sweep` family) |
| Cost tiers | 0.00 / 0.02 / 0.05 — diagnostic only, never evidence |

**Phase-2 (honest machinery).** Per-market spread, size-aware impact, DSR. Three measurements:

| Configuration | OOS net | Read |
|---|---|---|
| entry 3.5, flat real taker, $100/leg | +$187 | inside ±$212 → statistically zero |
| entry 3.5, per-market spread, $100/leg | **+$157.22** | still inside ±$212 |
| entry 3.5, spread **+ impact**, $1,000/leg | **−$50,669.90** | gate B5 fails hard |

And the decisive structural finding: **the gross edge lives in the thinnest markets**, so filtering
up to liquid names destroys it rather than saving cost (+$2,554 → −$183 at a ≥$100k/hr floor).

**The gap:** every one of those rows fixes entry at 3.5. The size ladder was measured on *one*
entry threshold, and the entry sweep was measured at *one* size.

---

## 2. The mechanism — why the interaction could invert

Two quantities scale differently with per-leg size **Q**:

- **Gross per trade ∝ Q** — linear.
- **Friction per trade = spread (∝ Q) + impact (∝ Q^1.5)** — superlinear.

So raising size always hurts the ratio. But per-trade *gross* is itself a function of the entry
threshold, and it rises fast: phase-1's own sweep shows in-sample gross/trade going
**$0.60 → $1.19 → $1.98 → $3.03** as entry goes 3.0 → 3.5 → 3.75 → 4.0 (`strategy.md:162-167`).

Phase-1 **rejected** entry 4.0 — "a vanity metric", 387 trades making only $1,020 versus 3.5's
$2,307. That rejection was correct **at $100/leg**, where friction is a flat ~$0.40/trade and total
P&L is dominated by trade *count*. At $1,000/leg friction is ~$9.93/trade — **32× higher** — and
the binding constraint flips from count to per-trade quality. A config that phase-1 discarded for
trading too rarely is precisely the shape that survives a per-trade tax.

That is the hypothesis. It follows from phase-2's own cost model, and it has never been measured.

**Derived per-trade economics** (from the documented aggregates, not new assumptions):

| Per-leg size | Gross/trade | Friction/trade | Ratio |
|---|---|---|---|
| $100 | $0.329 | $0.309 | 1.07 |
| $1,000 | $3.33 | $9.93 | 0.34 |

**Break-even at $1,000/leg requires gross/trade ≥ $9.93** — about **3×** what entry 3.5 delivers.

---

## 3. What the extrapolation predicts (stated before running, so the bar can't move)

Entry 3.5's OOS gross/trade ($0.329) is **27.8%** of its in-sample gross/trade ($1.19). Applying
that same out-of-sample haircut to the higher thresholds:

| Entry | In-sample gross/trade @$100 | Projected OOS @$100 | Projected OOS @$1,000 | vs $9.93 needed |
|---|---|---|---|---|
| 3.5 | $1.19 | $0.33 | $3.33 | ✗ (measured: −$50,670) |
| 3.75 | $1.98 | $0.55 | $5.52 | ✗ |
| 4.0 | $3.03 | $0.84 | $8.43 | ✗ — closer, still short |

**Prediction: entry 4.0 at $1,000/leg lands near break-even and still fails B3.** At an
intermediate size the arithmetic is friendlier (impact ∝ Q^1.5 shrinks fast) but the *totals* stay
tiny, because entry 4.0 trades so rarely — a few hundred OOS trades at a dollar or two of edge is
well inside the ±$212 noise floor.

Two further reasons to expect failure, both pre-stated:
1. **B4 (cross-span robustness).** Entry 3.5's OOS is carried entirely by s4; s2 and s3 are
   negative. Nothing suggests 4.0 fixes that.
2. **B3 (DSR).** Entry 4.0's thin trade count is exactly what the deflated Sharpe punishes, and
   `n_trials` grows with every run this campaign adds — the correction gets **stricter**, not
   looser (`backend/stats/significance.py:41-43`).

---

## 4. The proposed grid

### Constraint found while planning
`starting_capital` must scale **with** `usd_per_trade` to hold the concurrent-slot count constant
(the B5 run used $100k capital at $1,000/leg to keep the same 100 slots as the $100 baseline).
Campaign axes are expanded as a **Cartesian product** (`backend/backtest/campaign.py`), so those
two cannot be zipped in one spec — crossing them would silently vary slot count as well as size and
confound the result. **Therefore: one campaign per size tier**, with size and capital both fixed in
`base`, and entry as the only axis.

### Option A — the focused test (RECOMMENDED)

Two campaigns, 3 entry values × 3 OOS spans = **9 runs each, 18 total**.

```jsonc
// Campaign 1 — "entry-size-100"
{ "name": "entry-size-100",
  "windows": [
    {"label":"s2","start":"2025-11-07T00:00:00Z","end":"2026-03-01T00:00:00Z"},
    {"label":"s3","start":"2025-07-16T00:00:00Z","end":"2025-11-07T00:00:00Z"},
    {"label":"s4","start":"2025-03-24T00:00:00Z","end":"2025-07-16T00:00:00Z"}
  ],
  "axes": { "entry_threshold": [3.5, 3.75, 4.0] },
  "base": { "usd_per_trade": 100, "starting_capital": 10000,
            "exit_threshold": 0.5, "stop_threshold": 5.0, "pvalue_max": 0.01,
            "zscore_window": 21, "scan_window_days": 90, "trade_window_days": 30 },
  "cost_flags": { "per_market_slippage": true, "market_impact": true },
  "concurrency": 2 }

// Campaign 2 — "entry-size-1000": identical, but
//   "base": { "usd_per_trade": 1000, "starting_capital": 100000, ... }
```

- **entry 3.5 is included deliberately as the control** — same engine, same run, so the comparison
  against 3.75/4.0 is internal rather than against a figure from a different sweep.
- **`stop_threshold: 5.0`** avoids the degenerate `entry == stop` at entry 4.0; phase-1 used the
  same guard, and stop is a documented weak lever so it does not confound.
- Cost flags **ON** — mandatory, non-negotiable.
- New runs auto-stamp `phase=2`.

**Estimated runtime:** ~2–3h per config across s2–s4 on the 2-vCPU box → roughly **6–9h per
campaign**, so **12–18h total** at concurrency 2. An overnight job, run sequentially.

### Option B — add the intermediate size
Adds a third campaign at $250/leg (capital $25,000), +9 runs, +6–9h. Maps the impact curve where
Q^1.5 has not yet dominated. Only worth it if Option A's $1,000 tier lands closer to break-even
than §3 predicts.

### Option C — skip the campaign
§3's arithmetic already predicts failure, and §5's bar is unlikely to be cleared. Spending ~15h of
prod compute to confirm a prediction is a legitimate thing to decline. If the operator prefers, the
honest write-up in §3 stands on its own as the answer, and Task C closes as "settled analytically."

---

## 5. How every candidate will be judged (pre-stated, before any result exists)

`PHASE2_STRATEGY_PLAN.md` §1, unchanged and not negotiable after the fact:

| Gate | Threshold |
|---|---|
| **B1** | OOS only. s2/s3/s4 have zero overlap with the tuned window. In-sample results are inadmissible. |
| **B2** | Real per-market taker cost on all four fills. `PER_MARKET_SLIPPAGE` + `MARKET_IMPACT` on. |
| **B3** | OOS net ≥ **+$424** (2σ above the ±$212 noise floor) **or** DSR > 0.95. |
| **B4** | Non-negative in **≥2 of s2/s3/s4** — not carried by one lucky span. |
| **B5** | Survives market impact at real per-leg size. |

**Reporting commitment.** For every candidate I will report OOS net **per span**, the summed OOS
net, trade count, win rate, the Task-A cost decomposition (gross / fees / funding), and DSR — then
state plainly whether **any** config clears the bar. **Ranking on in-sample net is forbidden.** If
nothing clears it, that is the result and NO-GO stands.

---

## 6. Angles considered and rejected (so they are not silently skipped)

- **Hold-time caps to cut funding drag** (suggested in the kickoff, tied to Task A). **Rejected as a
  primary lever, on evidence.** `max_half_life_h` is documented **inert** — a 24h cap removes only
  ~4% of trades because admitted pairs already revert in under 24h. And funding scales with
  notional × time exactly as gross does, so its *relative* drag is size-independent; fees and impact
  dominate. Task A now makes funding visible per trade, so if the campaign's blotters show funding
  is materially larger than expected, this becomes worth revisiting on evidence — but proposing it
  now would be proposing a lever the docs already refute.
- **Liquidity/universe filters as an alpha lever.** Refuted decisively (§4 of the Phase-2 plan).
  Available as an honesty knob only.
- **Entry above 4.0.** The API caps `entry_threshold` at 4.0 (`routers/backtest.py:62`). Given that
  phase-1 found net *falling* from 3.5 to 4.0 at $100/leg, going higher would need a code change to
  test a region the trade-count collapse makes unpromising. Not proposed.
- **Funding-carry-aware pair selection / a different signal.** Genuinely untried and the most likely
  route to a real "yes" (`PHASE2_STRATEGY_PLAN.md` §7), but it is **new signal work**, not a grid —
  it needs an engine change and its own plan. Out of scope for a campaign-runner sweep; flagged here
  as the honest successor if Task C fails as predicted.

---

## 7. Execution checklist (only after grid approval)

1. Operator approves the grid (Option A / B / C).
2. **Separate** operator OK for the prod action.
3. Confirm prod is safe: `ENVIRONMENT=testnet`, and re-POST `/api/system/data-source` to
   `hyperliquid` if the api container has restarted (it resets to dydx).
4. `POST /api/backtest/campaigns` with the approved spec. Members auto-stamp `phase=2`.
5. **Monitor via `psql` in the postgres container, not HTTP** — the CPU-bound scan saturates the
   event loop on a 2-vCPU box.
6. Report against §5. No row is ever deleted; phase-1 rows are untouched.
