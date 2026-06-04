# 10. Consolidate the duplicated serde / per-leg-P&L / close-tail seams (Phase 10)

- **Status:** Accepted
- **Date:** 2026-06-04

## Context

Phase 10 is the hardening pass: run `improve-codebase-architecture`, address the
findings, and prepare for deploy. The architecture review surfaced three
**shallow** duplications that had accreted across Phases 5–9 — each a single small
rule copied into many modules, adding no leverage and three places a money-path
bug could diverge. All three were anticipated during earlier phases and tracked
as GitHub issues [#18](https://github.com/sauravs/statsArbBot/issues/18) (share the
per-leg signed-P&L core) and [#19](https://github.com/sauravs/statsArbBot/issues/19)
(dedupe the Prisma serialisation helpers), deliberately deferred here rather than
refactored mid-feature (the Phase 6/7/8 precedent: don't touch a proven path while
shipping a feature on top of it).

The review report (generated to the OS temp dir, not committed) ranked them:

1. **Prisma serde helpers** — `_iso` (datetime → ISO) and `_enum_value` (enum →
   `.value`) re-declared in five repositories. *Strong.*
2. **Per-leg P&L** — the rule `side_sign · (exit − entry) · size` (BUY +1 / SELL −1)
   spelled out three times (`trading/pnl`, `manual/pnl`, `simulation/costs`). *Strong.*
3. **Live pair-close tail** — "real P&L when both fills known, else `pnl=None`
   (never fabricated) → `close_trade` → notify" implemented in both
   `trading/exit._close_in_db` and `trading/engine.close_pair`. *Worth exploring,*
   with a caution: it lives on the live dYdX order path, which has never executed
   against a real exchange (the Phase-5a pre-production checkpoint).

## Decision

Extract one seam per duplication, keeping every change **behaviour-preserving** and
covered by the existing suite:

1. **`db/serde.py`** — `iso()` / `enum_value()`. The five repositories import them
   (aliased to the prior private names so call sites are untouched). The per-model
   `_to_dict` shapes stay where they are — only the leaf converters are shared.
2. **`statcore/pnl.py`** — `side_sign(side)` / `leg_pnl(side, entry, exit, size)`.
   This places the P&L sign rule in the **pure core** that already exists to keep
   algorithmic truth single-sourced (PRD §3, ADR-0007), alongside the signal logic
   it must agree with. The three P&L modules keep their distinct interfaces (live =
   units fixed at fill, manual = capital ÷ entry, sim = cost-modelled) and delegate
   the signed arithmetic. `simulation.costs._leg_pnl` stays as a thin positional
   adapter so its many call sites are unchanged.
3. **`trading/close.py::persist_closed_pair`** — the close-record tail (real-P&L-or-
   `None` + `close_trade` + notify). The exit manager's three branches and
   `close_pair` call it. The **conservative scope** recommended by the review: the
   *position-aware which-legs-to-close* logic stays at each call site (it genuinely
   differs — the exit manager already knows both legs are live; `close_pair`
   re-checks per leg), and `engine.abort_all` keeps its distinct whole-book flat
   ($0-P&L) close. Only the shared tail moves, capturing most of the locality at a
   fraction of the live-path blast radius.

Each new pure seam also gets its own focused unit tests (`test_db_serde.py`,
`test_statcore_pnl.py`) — the interface is the test surface.

## Consequences

- The "don't fabricate P&L" rule (the most safety-critical close-path invariant)
  and the P&L sign convention each live in exactly one verified place; the deletion
  test passes loudly for all three. Net ≈ −110 lines of duplicated logic.
- `statcore` broadens slightly from "cointegration + signals" to "+ the P&L sign
  rule." This is consistent with its charter as the single source of algorithmic
  truth reused by every path, and the rule is exactly that shape.
- **Deliberately not consolidated:** `replay/engine._close_remaining` vs
  `backtest/engine._close_window` (they run the *simulation* cost model over an
  in-memory `WorkingSimRepository`, not the live P&L path — sharing them would
  couple two proven historical paths for little leverage), and the `abort_all`
  flat-close. Issue #8 (synthetic-series recipe) remains low-priority test-only debt.
- The close-tail extraction is validated only by the `FakeTradeClient` /
  `FakeLiveRepository` integration tests, not against a real exchange — the
  Phase-5a pre-production checkpoint still stands (see `DEPLOYMENT.md` §7).
- Issues #18 and #19 are closed by the Phase-10 PR.
