# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-06-01

## Context

The statsArbBot rewrite makes several non-obvious, hard-to-reverse decisions (algorithm parameters, persistence strategy, abstraction boundaries). Future sessions and the `improve-codebase-architecture` skill need the *why*, not just the *what*, to reason safely about changes.

## Decision

We record architecturally significant decisions as Architecture Decision Records (ADRs) in `docs/adr/`, one file per decision, numbered sequentially, using a short MADR-style format (Context / Decision / Consequences). ADRs are immutable once accepted; a reversal is a new ADR that supersedes the old one.

## Consequences

- A durable, reviewable trail of intent that survives context resets.
- Slight overhead per significant decision.
- The architecture skill can be grounded in `CONTEXT.md` (domain) + `docs/adr/` (decisions).
