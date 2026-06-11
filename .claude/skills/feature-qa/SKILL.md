---
name: feature-qa
description: "Answer questions about statsArbBot's features, behavior, and design by reading the project docs first and the codebase only when needed. Use when the user asks how a feature works, why something behaves a certain way, what the bot does, or any 'what/how/why' question about this application."
trigger: /feature-qa
---

# /feature-qa

Answer a question about how this application (statsArbBot — a pairs-trading bot for dYdX v4)
works, behaves, or is designed — without the user re-explaining the project each time.

## Usage

```
/feature-qa <question>     # answer a feature/behavior/design question
/feature-qa                # if no question, ask the user what they want to know
```

## Source-of-truth read order (progressive disclosure)

Read only what the question actually needs. Stop early once you can answer confidently.

1. **`CONTEXT.md`** — domain language, core concepts, glossary. Start here for "what is X" / vocabulary.
2. **`PRD.md`** — product requirements: what the feature is *supposed* to do and why.
3. **`PLAN.md` / `PROGRESS.md`** — current build state, phase status, what's done vs. pending.
   (These move fast and can drift from `main` — treat as intent, verify against code if it matters.)
4. **`docs/*.md`** — pick the relevant one:
   - `docs/USER_GUIDE.md` — how a user operates the bot / dashboard.
   - `docs/TRADING_CONCEPTS.md` — plain-English trading/strategy explanations.
   - `docs/BACKTEST_PARAMETER_GUIDE.md` — backtest config and parameters.
   - `docs/DEPLOYMENT.md` / `docs/AWS_DEPLOYMENT.md` / `docs/CICD.md` — running, deploying, pipeline.
   - `docs/adr/` — architecture decision records (the "why" behind design choices).
5. **The codebase** — escalate here only when the docs don't answer it. Grep/read the specific
   module rather than loading broadly. Code is ground truth when it conflicts with docs.

## How to answer

- **Lead with the direct answer**, then briefly support it. Don't make the user dig.
- **Cite sources** as `file:line` (clickable) or `doc.md` so the user can verify.
- **Flag drift:** if docs say one thing and code does another, say so explicitly and trust the code.
- **Say "not documented"** rather than guessing; offer to dig into the code if they want certainty.
- Keep it tight. These are serial follow-up questions — match the depth of the question asked.

## Log every Q&A to `docs/QA.md` (required)

After answering, **append** the question and your answer to `docs/QA.md`. Never overwrite
existing entries — read the file and add a new entry at the bottom. Use this format:

```
## <YYYY-MM-DD> — <short question title>

**Q:** <the user's question, verbatim>

**A:** <your answer, including the file/doc citations>

---
```

- `docs/QA.md` is a **tracked file** — it is committed to `main` and promoted to `production`
  along with the rest of the repo. Commit it when the user asks you to commit changes.
- If `docs/QA.md` is missing, recreate it with a brief header before appending.

## Notes

- Don't rely on `graphify-out/` (it isn't built); use the docs + targeted code reads above.
- Background project facts live in CLAUDE.md and the auto-memory index — already in context.
