# statsArbBot — AWS EC2 Deployment Guide

**Status:** **Live** — deployed to AWS EC2 on **2026-06-09** for internal-team use (self-hosting; live AWS deploy was a PRD §1.2 non-goal the operator opted into). See [§0 Current deployment](#0--current-deployment) for the running setup; the sections below are the full host runbook.

> ⚠️ **Read [§7 Pre-Production / Mainnet Checklist](#7--pre-production--mainnet-checklist) before pointing this at real funds.** The live dYdX order path has never executed against a real exchange (the Phase-5a pre-production checkpoint); secrets in the dev `.env` are testnet-scoped and must be rotated before mainnet.

> 📋 **Branching, CI gate, and the staging→production promotion flow live in [CICD.md](./CICD.md).** This file is the *host runbook* (how the box runs); CICD.md is the *process* (how a change reaches the box).

---

## 0 · Current deployment

The live instance, so any session/teammate has the facts without re-discovery.
**Non-secrets only** — the SSH key and `.env` values are never committed.

| | |
|---|---|
| **Status / mode** | Live, **internal-team**. `ENVIRONMENT=testnet`, `SCAN_DATA_SOURCE=dydx` (live indexer); historical cache **seeded** (43 markets / ~463k OHLCV rows). **Not trading** (testnet, no real dYdX keys). |
| **Instance** | `t4g.large` (2 vCPU / 8 GB, Graviton/arm64), Ubuntu 26.04, 40 GB gp3. id `i-0702f459eda05918e`, region `us-east-1`. |
| **Static IP** | Elastic IP `32.194.15.173` (survives reboots). |
| **URL** | `https://ec2-32-194-15-173.compute-1.amazonaws.com` — nginx (host) terminates TLS on 443 → `127.0.0.1:3000`. **Self-signed** cert (one-time browser warning; AWS hostnames can't get Let's Encrypt). |
| **SSH** | `ssh -i <key>.pem ubuntu@32.194.15.173` (key is operator-local, not in repo). |
| **Security group** | inbound: 22 (operator IP only — dynamic, re-set "My IP" if it changes), 80+443 (all). 8000/5432 not public; also bound to `127.0.0.1` in compose. |
| **App on box** | repo at `~/statsArbBot`, tracks the **`production`** branch; runs `docker compose up -d` (postgres + api + ui, `restart: unless-stopped`); `.env` at `~/statsArbBot/.env` (mode 600). |

**Deploy a change** (the routine): merge to `main` → PR `main → production` → on the server:
```bash
cd ~/statsArbBot && git pull && docker compose up -d --build
```
`--build` is required: the `api` and `ui` services run **locally-built images**, so a
plain `docker compose up -d` would restart the *old* image and silently skip your code
change. `--build` is a no-op (cache hit) when nothing changed, so it's safe to always use.

**Go to live data:** set `SCAN_DATA_SOURCE=dydx` in `.env`, restart, then run
`python scripts/gapfill_cache.py` to seed the cache. **Real trading:** only after the
[§7 mainnet checklist](#7--pre-production--mainnet-checklist) (`ENVIRONMENT=mainnet`).

---

## 1 · Topology

A single EC2 instance hosts three long-running processes plus the trading-pass driver:

```
┌───────────────────────── EC2 (Ubuntu 22.04/24.04 LTS) ─────────────────────────┐
│                                                                                  │
│  nginx :443 ──► ui (next start) :3000 ──► /api/proxy ──► api (uvicorn) :8000     │
│       (TLS)                                  (injects X-API-Key)     │            │
│                                                                      ▼            │
│                                                          PostgreSQL 16 :5432      │
│                                                                                   │
│  cron ──► curl POST /api/live/entry-scan & /exit-manage   (drives live passes)    │
│  (APScheduler inside the api process drives real-time-sim ticks itself)           │
└───────────────────────────────────────────────────────────────────────────────┘
```

Two viable runtimes — pick one:

| Option | When | How |
|---|---|---|
| **A — venv + systemd + cron** *(this guide's primary path, per PLAN §8)* | Bare EC2, full control, lowest overhead | Python venv for the API, `next start` for the UI, both under `systemd`; `cron` drives the periodic live entry/exit passes. |
| **B — Docker Compose** | Want parity with local dev | `docker compose up -d` reuses the committed `docker-compose.yml` (postgres + api + ui). Still add nginx/TLS + the live-pass cron in front. |

The rest of this guide details **Option A**. Option B is a one-liner once Docker + the `.env` are on the box (see [§8](#8--option-b-docker-compose-on-ec2)).

---

## 2 · Prerequisites

- **EC2 instance:** **`t4g.large`** (2 vCPU / 8 GB, Graviton/ARM) — recommended default; runs the full stack including backtests with headroom. `t4g.medium` (4 GB) only if you run **no** backtests/fast-forward sweeps on the box. Enable T **unlimited** mode so a long backtest isn't throttled by burst credits. See [§2.1 Instance sizing](#21--instance-sizing-measured) for the rationale and tiers.
- **Root volume:** **40 GB gp3** SSD (not 5 GB). Docker images alone are ~6.3 GB; the rest covers DB growth, `pg_dump` backups, build cache, and logs — and avoids the disk-full failure mode.
- **OS:** Ubuntu 22.04 or 24.04 LTS (use the **arm64** AMI for `t4g`).
- **Security group:** inbound `443` (HTTPS) and `22` (SSH, ideally IP-restricted) only. **Do not** expose `8000` (API) or `5432` (Postgres) publicly — they stay bound to localhost / the instance.
- **DNS + TLS:** a domain pointing at the instance's Elastic IP for nginx + Let's Encrypt.
- **Toolchain:** Python 3.12, Node 18+ (for the Next.js UI and the Prisma CLI), PostgreSQL 16.

```bash
sudo apt update && sudo apt install -y \
  python3.12 python3.12-venv build-essential \
  postgresql-16 nginx certbot python3-certbot-nginx git curl
# Node 18 LTS (NodeSource) — for `next` and the global `prisma` CLI
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g prisma
```

### 2.1 · Instance sizing (measured)

Sizing is driven by the **measured** footprint of the running Compose stack, not a
guess. Snapshot (idle, single operator):

| Component | Idle RAM | Note |
|---|---|---|
| api (FastAPI/uvicorn) | **~893 MB** | the heavy tier — *before* any backtest |
| postgres 16 | ~330 MB | DB on disk ~356 MB (funding 204 + ohlcv 144) |
| ui (Next.js) | ~53 MB | light |
| **Total idle** | **~1.3 GB** | |
| Docker images | ~6.3 GB | api image alone ~2.5 GB (pandas/statsmodels/dYdX) |

**RAM is the binding constraint.** Walk-forward cointegration sweeps load ~40
markets × thousands of bars into pandas and run pairwise Engle-Granger / OU
regressions, so the api process spikes well past its ~893 MB idle. Therefore
2 GB (the old `t3.small`) **will OOM**, 4 GB is tight, and **8 GB is the
comfortable target**. CPU is not the constraint — the bot is mostly idle with
periodic bursts — so 2 vCPU suffices.

| Tier | Instance | vCPU / RAM | ~$/mo (on-demand) | When |
|---|---|---|---|---|
| Minimum | `t4g.medium` | 2 / 4 GB | ~$25 | Live-trading only, **no** backtests on-box (OOM-risky otherwise) |
| **Recommended** | **`t4g.large`** | **2 / 8 GB** | **~$49** | Full stack incl. backtests, with headroom |
| Heavy sweeps | `t4g.xlarge` / `m7g.large` | 4/16 or 2/8 (non-burst) | ~$98 / ~$60 | Frequent/parallel backtests, or to avoid burst credits entirely |

Notes:
- **Graviton (`t4g`/`m7g`, ARM64)** is ~20–40% better price/perf than x86
  (`t3.large` ≈ $61/mo). The whole stack (Python, Node, Postgres, Docker, Prisma,
  dYdX client) runs natively on ARM64 — just build the images **on the instance**
  (or multi-arch); the Dockerfiles build from source, so this is trivial.
- Add a **2 GB swapfile** as an OOM cushion — turns a backtest memory spike into
  "slow" rather than "killed".
- A trading bot runs 24/7, so a **1-year Compute Savings Plan / Reserved** cuts
  ~30–40% (`t4g.large` → ~$30/mo).
- Use **gp3** (cheaper than gp2; 3000 IOPS / 125 MB/s baseline included).
- Optional later: offload Postgres to managed **RDS `db.t4g.micro`** and shrink
  the app box. For a single operator, one box with local Postgres is simpler and
  cheaper to start.

> Figures measured Jun 2026 against the live Colima/Compose stack (43 markets,
> ~463k OHLCV bars, ~766k funding rows). Re-measure (`docker stats`,
> `pg_database_size`) as the dataset grows.

---

## 3 · PostgreSQL

```bash
sudo -u postgres psql <<'SQL'
CREATE USER statsarb WITH PASSWORD 'CHANGE_ME_STRONG';
CREATE DATABASE statsarb OWNER statsarb;
SQL
```

Keep Postgres bound to `localhost` (the default `listen_addresses = 'localhost'`). The API connects over the loopback; nothing else needs the DB.

`DATABASE_URL=postgresql://statsarb:CHANGE_ME_STRONG@localhost:5432/statsarb`

---

## 4 · Backend (FastAPI + Prisma) — venv + systemd

```bash
sudo useradd -r -m -d /opt/statsarb -s /bin/bash statsarb
sudo -u statsarb -i
git clone https://github.com/sauravs/statsArbBot.git /opt/statsarb/app
cd /opt/statsarb/app/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # includes dydx-v4-client + python-telegram-bot
prisma generate --schema prisma/schema.prisma
prisma migrate deploy --schema prisma/schema.prisma   # applies migrations 0001–0008
```

> `prisma generate` resolves the target Python from `PATH` — run it with the venv **active** (or the venv first on `PATH`), or it generates the client into a stray interpreter (a known local gotcha, see PROGRESS Phase 2 notes).

**Secrets** live in `/opt/statsarb/app/.env` (gitignored, mode `600`, owned by `statsarb`). Populate from `.env.example` — see [§6](#6--environment--secrets).

**systemd unit** `/etc/systemd/system/statsarb-api.service`:

```ini
[Unit]
Description=statsArbBot API (FastAPI/uvicorn)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=statsarb
WorkingDirectory=/opt/statsarb/app/backend
EnvironmentFile=/opt/statsarb/app/.env
# Reach the repo-root .env explicitly; the CLI/runtime do not auto-find it.
ExecStart=/opt/statsarb/app/backend/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The FastAPI **lifespan** wires up the Prisma client, the APScheduler (real-time-sim ticks + RUNNING-session re-registration), and — only when `TELEGRAM_ENABLED` — the Telegram approval gate/alerter. Bind to `127.0.0.1`; nginx terminates TLS and the UI proxies to it.

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now statsarb-api
```

---

## 5 · Frontend (Next.js) — build + systemd

```bash
cd /opt/statsarb/app/ui
npm ci
npm run build      # next build (App Router, standalone)
```

`/etc/systemd/system/statsarb-ui.service`:

```ini
[Unit]
Description=statsArbBot UI (Next.js)
After=network.target statsarb-api.service

[Service]
User=statsarb
WorkingDirectory=/opt/statsarb/app/ui
# Only the three values the Next tier needs — never inject backend secrets here.
Environment=API_URL=http://127.0.0.1:8000
Environment=NODE_ENV=production
EnvironmentFile=/opt/statsarb/app/ui/.env.production   # DASHBOARD_PASSWORD + DASHBOARD_JWT_SECRET
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The UI tier holds **only** `DASHBOARD_PASSWORD`, `DASHBOARD_JWT_SECRET`, and `API_URL`. The dYdX key, Telegram token, and `DATABASE_URL` must **never** reach the UI process (the browser talks only to the Next.js `/api/proxy`, which injects the shared `X-API-Key`; mirrors the docker-compose split).

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now statsarb-ui
```

### nginx + TLS

```nginx
server {
    server_name bot.example.com;
    location / { proxy_pass http://127.0.0.1:3000; proxy_set_header Host $host; }
}
```
```bash
sudo certbot --nginx -d bot.example.com   # provisions + auto-renews the cert
```

---

## 6 · Environment & Secrets

Copy `.env.example` → `.env` and fill every value. Grouped highlights (full list in `.env.example`):

| Variable | Purpose | Production note |
|---|---|---|
| `ENVIRONMENT` | `testnet` (forward_test) or `mainnet` (production) | **Defaults to `testnet`.** Set `mainnet` only after the checklist below. |
| `DYDX_WALLET_API_KEY` / `DYDX_PRIVATE_KEY` | dYdX account credentials | **Rotate to fresh mainnet keys before production.** `0600`, never logged, never committed. |
| `DASHBOARD_PASSWORD` | 6-digit login passcode | **Required** when `ENVIRONMENT != testnet` (config enforces this at startup). |
| `DASHBOARD_JWT_SECRET` | signs the session JWT | Long random string; rotate from the placeholder. |
| `DATABASE_URL` | Postgres DSN | loopback only. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | enable the live approval gate + CODE-RED alerts | Set **both** to non-placeholder values to flip `TELEGRAM_ENABLED`; leave either as its placeholder to keep the auto-approve gate + logging alerter. |
| `TELEGRAM_APPROVAL_TIMEOUT_MIN` | minutes before a signal auto-rejects | `0` = reject-immediately kill-switch. |
| `SCAN_DATA_SOURCE` | `dydx` (live mainnet indexer) or `fake` (offline demo) | Use `dydx` in production; price/candle data is always read from mainnet even in testnet mode. |

Secrets hygiene: `.env` is gitignored and was never committed (verified Phase 10); only `.env.example` (placeholders) is tracked. Restrict: `chmod 600 .env && chown statsarb:statsarb .env`.

---

## 7 · Pre-Production / Mainnet Checklist

The bot must **not** be treated as proven against real funds until all of these are done:

1. **Rotate every secret** out of the dev `.env`: fresh dYdX mainnet wallet key, a new Telegram bot token, a strong `DASHBOARD_PASSWORD`, and a long random `DASHBOARD_JWT_SECRET`. (Also drop the unused `EXA_API_KEY` dev leftover.)
2. **Validate live on testnet first.** Run a full `forward_test` cycle on dYdX testnet with a funded subaccount: confirm an entry opens a real position, the exit/stop closes it, and the trade records correct P&L. This closes the literal Phase-5a gate, which the automated suite (all `FakeTradeClient`) cannot.
3. **Fix [issue #16](https://github.com/sauravs/statsArbBot/issues/16)** (resync `wallet.sequence` after a failed dYdX broadcast) — it lives in the never-executed live order path and blocks reliable live trading.
4. **Set risk controls:** consider [#17](https://github.com/sauravs/statsArbBot/issues/17) (max-open-pairs cap) and confirm `USD_MIN_COLLATERAL` for the account.
5. **Enable Telegram approval** (`TELEGRAM_ENABLED`) so live entries/exits require a human ✅ before execution; verify the live `PtbBotClient` polling loop against a real bot (untested in the automated gate — PTB is exercised only via mocks). Note [#28](https://github.com/sauravs/statsArbBot/issues/28): an approval await currently holds the engine lock — review before enabling alongside frequent aborts.
6. **Seed `OhlcvCache`** if running backtests/fast-forward on the box (see §9).
7. Only then set `ENVIRONMENT=mainnet` and restart `statsarb-api`.

---

## 8 · Driving live passes with cron (Option A)

Live entry/exit are explicit `POST` passes (the testable seam that replaced the prototype's cron flags; APScheduler automates only the real-time-sim ticks). On EC2, `cron` drives them. The endpoints require the shared API key, so call them through the authenticated surface — e.g. a small wrapper script that reads `API_KEY` from the env and curls `127.0.0.1:8000`:

```cron
# /etc/cron.d/statsarb  — runs as the statsarb user
*/15 * * * * statsarb /opt/statsarb/app/ops/pass.sh entry-scan  >> /var/log/statsarb/pass.log 2>&1
*/5  * * * * statsarb /opt/statsarb/app/ops/pass.sh exit-manage >> /var/log/statsarb/pass.log 2>&1
```

`pass.sh` is a 3-line `curl -H "X-API-Key: $API_KEY" -X POST http://127.0.0.1:8000/api/live/$1` wrapper (create under `ops/`, mode `700`). Cadence is the operator's call — entry less often, exit more often so positions are managed promptly. The exit pass also reconciles/orphan-closes, so keep it running even when the bot is deactivated.

> A deactivated session still allows `exit-manage`/`abort`, so positions are always closable. The real-time-sim scheduler runs **inside** the api process — no cron needed for sims.

---

## 9 · One-time data seed (backtest / fast-forward)

Backtests and fast-forward sims read historical candles from `OhlcvCache`. Seed it once (the data files are reproducible via the refresh script; `data/` is gitignored):

```bash
cd /opt/statsarb/app/backend && source .venv/bin/activate
export DATABASE_URL="$(grep -E '^DATABASE_URL=' ../.env | cut -d= -f2-)"
python scripts/ingest_historical.py            # cleans + seeds OhlcvCache/FundingRateCache
# To refresh from dYdX first: python scripts/refresh_dydx_data.py
```

**Keeping the cache current.** Once seeded, top the live DB cache up to the present
straight from the dYdX indexer with the resumable, idempotent maintenance job:

```bash
cd /opt/statsarb/app/backend && source .venv/bin/activate
python scripts/gapfill_cache.py                 # fetch each market's missing tail → now
python scripts/gapfill_cache.py --dry-run        # show the plan, fetch nothing
```

It only fetches each active market's missing tail, never deletes on empty, and is
safe to re-run / resilient to disconnects (waits out an outage via a BTC sentinel
rather than declaring false completion). Delisted markets keep their history but
can't be extended. Schedule it (cron) to keep backtests/fast-forward on fresh data.

Live trading and real-time simulation do **not** need the seed (they read live prices).

---

## 10 · Option B — Docker Compose on EC2

If you prefer parity with local dev: install Docker + the Compose plugin, place the filled `.env` at the repo root, then:

```bash
cd /opt/statsarb/app && docker compose up -d --build
```

The committed `docker-compose.yml` brings up postgres + api (runs `prisma migrate deploy` on start) + ui. Still front it with nginx/TLS and add the §8 live-pass cron (point it at the host-mapped `:8000`). Note the compose file maps `5432`/`8000` to the host for dev convenience — remove those port mappings (or firewall them) on a public instance.

---

## 11 · Operations

- **Logs:** `journalctl -u statsarb-api -f` / `journalctl -u statsarb-ui -f`; live-pass cron logs at `/var/log/statsarb/pass.log`.
- **Upgrade:** `git pull` → `pip install -r requirements.txt` → `prisma generate && prisma migrate deploy` → `npm ci && npm run build` → `systemctl restart statsarb-api statsarb-ui`.
- **Backups:** `pg_dump statsarb` on a schedule; the DB holds all live/sim/manual/backtest state (DB-backed, no flat files — ADR-0003).
- **CODE-RED:** if the failsafe close fails the bot emits a CODE-RED alert (Telegram when enabled, else the logs). Treat it as "a position may be live and unhedged" — check the dYdX account directly.

---

*This document is a runbook, not an executed deployment. Validate every step on testnet before mainnet.*
