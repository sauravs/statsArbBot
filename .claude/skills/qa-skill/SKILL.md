---
name: qa-skill
description: "Answer a question about statsArbBot (features, UI, backtest/trading behavior, design) and LOG the question + answer to docs/QA.md. Use when the user types /qa-skill, or asks a what/how/why question they want recorded in the project Q&A log."
trigger: /qa-skill
---

# /qa-skill

Answer the user's question about this application (statsArbBot — a pairs-trading /
statistical-arbitrage bot for dYdX v4 perps), then **log the Q&A to `docs/QA.md`**.

Use this when the user wants a question *answered and recorded*. It is the logging
counterpart to `/feature-qa`; both write to the same `docs/QA.md` log.

## Usage

```
/qa-skill <question>     # answer the question, then append it + the answer to docs/QA.md
/qa-skill                # if no question is given, ask the user what they want to know
```

## Source-of-truth read order (progressive disclosure)

Read only what the question needs; stop early once you can answer confidently. Code is
ground truth when it conflicts with docs.

1. **`CONTEXT.md`** — domain language, core concepts, glossary. Start here for "what is X".
2. **`PRD.md`** — what a feature is *supposed* to do and why.
3. **`PLAN.md` / `PROGRESS.md`** — current build state (fast-moving; treat as intent).
4. **`docs/*.md`** — pick the relevant guide:
   - `docs/USER_GUIDE.md` — operating the bot / dashboard.
   - `docs/TRADING_CONCEPTS.md` — plain-English trading/strategy explanations.
   - `docs/BACKTEST_PARAMETER_GUIDE.md` — backtest config & parameters.
   - `docs/DEPLOYMENT.md` / `docs/AWS_DEPLOYMENT.md` / `docs/CICD.md` — running & deploying.
   - `docs/adr/` — architecture decision records (the "why").
5. **The codebase** — escalate here when docs don't answer it. For trading/backtest
   *behavior* questions, the canonical signal logic is `backend/statcore/signals.py`
   (`evaluate_entry` / `evaluate_exit` — entry/exit/stop and exit-reason rules), and P&L
   accrual is in `backend/backtest/engine.py` / `backend/simulation/engine.py`. Grep the
   specific module rather than loading broadly.

## How to answer

- **Lead with the direct answer**, then briefly support it. Don't make the user dig.
- **Cite sources** as `file:line` (clickable) or `doc.md`.
- **Flag drift:** if docs and code disagree, say so and trust the code.
- **Say "not documented"** rather than guessing.
- Keep it tight and match the depth of the question.

## Log every Q&A to `docs/QA.md` (required)

After answering, **append** the question and answer to `docs/QA.md` — never overwrite.
Read the file, add a new entry at the bottom, using this format:

```
## <YYYY-MM-DD> — <short question title>

**Q:** <the user's question, verbatim>

**A:** <your answer, including file/doc citations>

---
```

- Use today's date (it's provided in the session context) for `<YYYY-MM-DD>`.
- `docs/QA.md` is a **tracked file** — committed to `main` and promoted to `production`.
  Commit it when the user asks you to commit.
- If `docs/QA.md` is missing, recreate it with a brief header before appending.
- Note: on this macOS (case-insensitive) filesystem, `qa.md` and `QA.md` are the **same
  file** — always write to `docs/QA.md`.

## Notes

- Don't rely on `graphify-out/` (not built); use the docs + targeted code reads above.
- Background project facts live in `CLAUDE.md` and the auto-memory index — already in context.
