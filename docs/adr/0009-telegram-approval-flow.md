# 9. Telegram approval flow (Phase 9.0)

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

Phase 9 replaces the stub `ApprovalGate` / `Alerter` (ADR-0004) with the real
Telegram human-in-the-loop flow (PRD F9.1): a live signal must prompt the operator
in Telegram and execute only on ✅, skipping on ❌ or timeout. Phase 9 is split into
**9.0 — approval flow + alerter** (this ADR) and **9.1 — commands** (`/status`,
`/balance`, …). Two constraints shaped the design:

1. **No engine surgery.** Entry/exit already `await gate.request(signal)` and route
   CODE-RED through `alerter` (Phase 5a). The Telegram pieces must drop in behind
   those seams via `set_approval_gate` / `set_alerter` only.
2. **Testable without the library and without a network.** `python-telegram-bot`
   (PTB) is *not* installed in the venv — same posture as `dydx-v4-client`. The
   approval logic must be exercisable end-to-end with a fake.

## Decision

1. **Package named `telegrambot/`, not `telegram/`.** `telegram` is PTB's import
   name; a sibling package by that name on `sys.path` (`backend/`) would shadow the
   library. (The reference prototype hit this and used `telegram_bot.py`; PLAN §3's
   aspirational `telegram/` is overridden here, consistent with prior pragmatic
   deviations.)
2. **A `BotClient` seam isolates PTB.** The gate and alerter depend only on a small
   `BotClient` protocol (`send_approval_request` / `edit_message` / `send_message`).
   `PtbBotClient` is the one place that imports PTB (lazily) and builds the inline
   ✅/❌ keyboard. Tests inject a `FakeBotClient`, so the whole approve/reject/timeout
   flow runs in-process with no PTB and no network.
3. **Blocking-future approval.** `TelegramApprovalGate.request` registers an
   `asyncio.Future` under a random token, embeds the token in the buttons'
   `callback_data`, sends the prompt, and awaits the future under
   `asyncio.wait_for(timeout)`. A button tap → the PTB `CallbackQueryHandler` parses
   the token and calls `gate.resolve(token, approved)` → the future completes →
   `request` returns. **Timeout, a failed send, and a zero/negative timeout all
   fail safe to `False`** (skip the signal) — the conservative default for money.
   The engine serialises passes behind one lock, so only one approval is ever
   outstanding, but futures are keyed by token regardless.
4. **Alerter is unconditionally non-raising.** `TelegramAlerter` swallows/logs send
   failures itself (not only relying on `PtbBotClient`), honouring the `Alerter`
   contract so a dead Telegram channel can never abort a trading pass — least of all
   the CODE-RED path.
5. **Install in the FastAPI lifespan, best-effort, DB-independent.** `start_telegram`
   runs only when `TELEGRAM_ENABLED` (both token and chat id set to non-placeholder
   values); otherwise the `AutoApproveGate` / `LoggingAlerter` defaults stay, so
   every non-live phase keeps working. PTB missing, a bad token, or a network error
   are logged and leave the defaults untouched.

## Consequences

- The Telegram approval flow drops in with zero changes to `entry.py` / `exit.py` /
  `engine.py` — only the lifespan installs it (ADR-0004 vindicated).
- Approve / reject / timeout / failed-send / kill-switch are all unit-tested, and an
  integration test drives a real `TelegramApprovalGate` through `scan_for_entries` /
  `manage_exits` to prove the decision actually gates order placement — all without
  PTB installed or a live exchange.
- The live `PtbBotClient` + PTB `Application` polling loop are **not** exercised by
  the automated gate (PTB isn't installed; the real connection needs a bot token).
  Validating against a real Telegram bot is a manual step, mirroring the unvalidated
  live dYdX order path (Phase 5a pre-production checkpoint).
- F9.2 commands (`/status`, `/balance`, `/positions`, `/pairs`, `/cancel`,
  `/activate`, `/deactivate`) reuse the same `Application` instance in Phase 9.1.
- **Known limitation (issue #28):** because the gate's `request` blocks awaiting a
  human tap and the engine calls it *inside* its process lock, a pending entry
  approval blocks `exit-manage` / `abort-all` for the same (exchange, mode) for up
  to the approval timeout. Only bites when Telegram is enabled (live trading, itself
  gated by the Phase-5a pre-production checkpoint). Deferred to #28: move the
  approval `await` outside the engine lock (approve first, then lock to place
  orders).
