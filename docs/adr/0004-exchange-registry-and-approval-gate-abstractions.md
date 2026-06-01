# 4. Exchange-registry and approval-gate abstractions

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

This phase targets dYdX v4 only, but Binance/Hyperliquid are planned later. Separately, the trading engine must run with no human approval (tests, early phases) now and with Telegram human approval later — without rewriting the engine. Baking either concern directly into the engine would couple it to choices that change later (this coupling caused the prototype's `connect_dydx`/`create_dydx_connection` mismatch and Telegram instability).

## Decision

1. **Exchange registry:** exchanges sit behind a common interface registered in a registry. dYdX v4 is fully implemented; Binance and Hyperliquid remain `NotImplementedError` stubs flagged `integrated=false`. Adding an exchange later means implementing the interface, not touching the engine.
2. **Approval gate as an interface:** the trading engine consults an `ApprovalGate` interface before executing a signal. A **stub** implementation (`approve_all` / `reject_all`) is used through Phase 8; the **Telegram** implementation drops in at Phase 9 with no engine changes.

## Consequences

- New exchanges and the Telegram gate integrate without engine surgery.
- The engine is testable in isolation with a stub gate and mocked exchange client.
- A thin amount of indirection now, in exchange for clean extension later.
