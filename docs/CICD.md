# Branching, CI & promotion

How a change flows from a local branch to production. This governs **process**
(branches, CI gate, who approves a release); the **host runbook** (how the box
itself is provisioned/run on EC2) lives in [DEPLOYMENT.md](./DEPLOYMENT.md).

The one-paragraph version is mirrored in `.claude/CLAUDE.md` so every session
follows it by default.

## Branching model — trunk + promotion

GitFlow is too heavy for this project. We use a trunk with an explicit promotion
gate:

| Branch             | Role                                | Deploys to              |
| ------------------ | ----------------------------------- | ----------------------- |
| `fix-*` / `feat-*` | short-lived work, one per issue     | nothing (CI runs on PR) |
| `main`             | integration trunk, **always green** | **staging** (auto)      |
| `production`       | vetted releases only                | **production** (manual) |

**Flow**

1. Branch off `main`: `fix-<slug>` for a bug, `feat-<slug>` for a feature.
2. Open a PR into `main`. CI must pass (see below).
3. Merge to `main` → auto-deploys to **staging**.
4. Validate on staging.
5. **Promote**: PR `main → production` (or fast-forward). Merging to `production`
   starts the prod deploy, which **pauses for manual approval** on the
   `production` GitHub Environment. That approval is the "we agree it's ready"
   gate the operator asked for.

Rules: promotion is always `main → production`; never commit straight to
`production`; never let `production` get ahead of `main`. A hotfix is just a
normal fix branch → `main` → promote.

## CI gate — `.github/workflows/ci.yml`

Runs on every PR/push to `main` and `production`:

- **backend** — starts a Postgres service, `prisma generate` + `migrate deploy`,
  then `pytest`. (This is why the DB-dependent tests that fail on a bare host
  pass here — CI gives them a real DB.)
- **frontend** — `npm ci`, `tsc --noEmit`, `npm run lint`, `npm run build`.

Playwright E2E needs the full compose stack; run it locally (`--workers=1`,
containerized) before promoting — not in CI yet.

## Deploy workflows (skeletons)

- `deploy-staging.yml` — on push to `main`: build + push images to **GHCR**, then
  deploy to the staging host.
- `deploy-production.yml` — on push to `production`: build + push, **back up the
  DB (`pg_dump`) before migrating**, deploy, smoke-check `/health`.

Image build/push works out of the box (GHCR via `GITHUB_TOKEN`). The host-deploy
steps are **placeholders gated off** until you opt in — see below. They target
the docker-compose topology in DEPLOYMENT.md §10 (`docker compose pull && up -d`;
the api container runs `prisma migrate deploy` on start).

## What actually protects production (not the branch)

A branch is only the deploy *trigger*. Real safety:

- **Environment isolation** — staging and production are separate hosts with
  separate Postgres and separate domains. Staging must never touch the prod DB.
- **Secrets out of git** — `.env` stays gitignored; only `.env.example` is
  tracked (DEPLOYMENT.md §6). In CI/CD, secrets live in **GitHub Environments**,
  never in the repo.
- **Mainnet safety** — prod is a live trading bot. A deploy leaves it
  safe/disabled; going live is `ENVIRONMENT=mainnet` + activation after the
  DEPLOYMENT.md §7 checklist. Never a deploy side effect.
- **Recoverable migrations** — prod deploy takes a `pg_dump` before `migrate
  deploy`.

## Enabling the pipelines

No-op until you opt in. Settings → Secrets and variables → Actions → **Variables**:

| Variable            | Purpose                                   |
| ------------------- | ----------------------------------------- |
| `DEPLOY_STAGING`    | `true` to enable the staging host deploy  |
| `DEPLOY_PRODUCTION` | `true` to enable the production deploy     |

Per-environment **secrets** (Settings → Environments → `staging` / `production`):
`*_SSH_HOST`, `*_SSH_USER`, `*_SSH_KEY` for the deploy SSH. Add **required
reviewers** on the `production` environment (the manual approval gate). Then fill
the `TODO` deploy steps in the two deploy workflows.

> Swapping to managed AWS later (ECR + ECS Fargate + RDS) only changes the deploy
> *steps* and the backup (RDS snapshot instead of `pg_dump`) — the branching
> model and CI gate are unchanged.
