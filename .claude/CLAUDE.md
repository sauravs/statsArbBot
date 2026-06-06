# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# Branching & deployment (follow by default)
Full detail: `docs/CICD.md` (process) + `docs/DEPLOYMENT.md` (host runbook).
- **Trunk + promotion.** `main` = always-green integration trunk → auto-deploys to **staging**. `production` = vetted releases only → deploys to **production** behind a **manual approval** gate.
- **Work** happens on short-lived `fix-<slug>` / `feat-<slug>` branches off `main`, one per issue, via PR. CI (`.github/workflows/ci.yml`) must pass before merge.
- **Promote** only `main → production` (PR or fast-forward) after validating on staging. Never commit straight to `production`; never let `production` get ahead of `main`. Hotfix = normal fix branch → `main` → promote.
- **production = dYdX mainnet (real money).** A deploy must leave the bot safe/disabled; going live (`ENVIRONMENT=mainnet` + activation) is deliberate, per `docs/DEPLOYMENT.md` §7 — never a deploy side effect.
- **Never commit secrets.** `.env` stays gitignored (only `.env.example` is tracked); CI/CD secrets live in GitHub Environments. Prod deploy takes a `pg_dump` before `prisma migrate deploy`.
