# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# Branching & deployment (follow by default)
Full detail: `docs/CICD.md` (process) + `docs/DEPLOYMENT.md` (host runbook).
- **Trunk + promotion.** `main` = always-green integration trunk; `production` = vetted releases that the live EC2 server runs (deployed via `git pull` on the `production` branch). A `staging` auto-deploy exists in the pipeline but is a **dormant skeleton — there is NO live staging environment yet**, so end-to-end testing happens on the **local dev Docker stack**.
- **Work flow:** short-lived `fix-<slug>` / `feat-<slug>` branch off `main`, one per issue → implement → **test end-to-end on the local dev stack** → open a PR (CI `.github/workflows/ci.yml` must pass).
- **Operator approval is the gate — do NOT skip it.** Never merge to `main`, and never promote `main → production`, without the operator's explicit OK. Promotion is always `main → production` (never commit straight to `production`; never let it get ahead of `main`). Deploy to the server only after approval: `cd ~/statsArbBot && git pull && docker compose up -d --build` (on the `production` branch — `--build` is required because `api`/`ui` are locally-built images; without it the old image restarts and the code change is silently skipped). Live deployment facts: `docs/DEPLOYMENT.md` §0.
- **production = dYdX mainnet (real money).** A deploy must leave the bot safe/disabled; going live (`ENVIRONMENT=mainnet` + activation) is deliberate, per `docs/DEPLOYMENT.md` §7 — never a deploy side effect.
- **Never commit secrets.** `.env` stays gitignored (only `.env.example` is tracked); CI/CD secrets live in GitHub Environments. Prod deploy takes a `pg_dump` before `prisma migrate deploy`.
