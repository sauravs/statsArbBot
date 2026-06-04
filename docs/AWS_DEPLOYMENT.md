# statsArbBot — AWS EC2 Deployment (Step-by-Step, from a fresh AWS account)

**Audience:** the operator, deploying **frontend + backend on one EC2 instance** using the repo's committed `docker-compose.yml`. This is the beginner-friendly, click-by-click companion to `DEPLOYMENT.md` (which is the broader reference). Where they overlap, this doc wins for the AWS specifics.

> 🟢 **Start on testnet.** This whole guide assumes `ENVIRONMENT=testnet` (no real money). Do **not** switch to `mainnet` until you've completed the [§11 pre-production checklist](#11--before-mainnet-real-money). A trading bot on a misconfigured box is a money bug.

---

## 0 · How this codebase interacts with AWS (read this first)

It helps to know what AWS *is* and *isn't* doing here:

- **AWS gives you a bare Linux computer (EC2) + a network + a firewall + storage.** That's it. AWS does **not** know anything about Python, Next.js, or trading — it just runs a VM you control.
- **Docker does all the real work.** The repo ships two `Dockerfile`s (`backend/Dockerfile`, `ui/Dockerfile`) and a `docker-compose.yml` that builds and runs **three containers** on a private network inside the VM:

```
┌──────────────────── EC2 instance (Ubuntu) — one Docker network ────────────────────┐
│                                                                                      │
│   ┌──────────────┐      ┌─────────────────────┐      ┌──────────────────────────┐    │
│   │ ui (Next.js) │ ───► │ api (FastAPI/uvicorn)│ ───► │ postgres:16              │    │
│   │  :3000       │ proxy│  :8000  + APScheduler│      │  :5432                   │    │
│   │              │ +X-API-Key  + Telegram loop │      │  volume: postgres_data   │    │
│   └──────┬───────┘      └─────────────────────┘      └──────────────────────────┘    │
│          │                                            (data persists on the EBS disk) │
└──────────┼───────────────────────────────────────────────────────────────────────────┘
           │  (you reach the UI from your browser)
        Browser
```

- **Networking:** the three containers talk to each other by service name on Docker's private network (`api` reaches `postgres:5432`; the `ui` proxy reaches `api:8000`). Your **browser** only ever talks to the **`ui`** — it never hits the API or DB directly. The Next.js `/api/proxy` injects the shared `X-API-Key` server-side.
- **Data:** Postgres stores everything (live/sim/manual/backtest state — DB-backed, no flat files) in a Docker **volume** (`postgres_data`) that lives on the instance's disk (EBS). It survives `docker compose restart` and reboots; `docker compose down -v` **wipes** it.
- **Secrets:** live in a `.env` file **on the instance** (mode `600`). They are never baked into the images and never leave the box. The dYdX key / Telegram token stay on the backend side; the UI container only gets `DASHBOARD_PASSWORD`, `DASHBOARD_JWT_SECRET`, `API_URL`.
- **The AWS "firewall" = Security Group.** This is the one AWS-specific security control that matters: it decides which ports the internet can reach. We open only SSH + web; we keep Postgres (5432) and the API (8000) **private**.

**Things you do NOT need** (for a single operator): ECR, ECS/EKS, RDS, load balancers, Terraform. One `t3.small` + `docker compose up` is the whole deployment. (You can graduate to RDS/ALB later; noted in §12.)

---

## 1 · Create your AWS account

1. Go to <https://aws.amazon.com/> → **Create an AWS Account**. You'll need an email, a credit card (charged only beyond free-tier/usage), and a phone number.
2. Choose the **Basic (free) support plan**.
3. **Secure the root account immediately:**
   - Sign in as root → **IAM** → enable **MFA** on the root user (use an authenticator app).
   - **Don't use root for daily work.** Create an IAM admin user for yourself: **IAM → Users → Create user** → attach the **AdministratorAccess** policy → enable MFA on it too. Sign out of root; use this IAM user from now on.
4. **Set a billing alarm** so you're never surprised: **Billing → Budgets → Create budget** → a small monthly cost budget (e.g. $20) with an email alert.

> 💡 **Region:** pick one close to you for low dashboard latency (e.g. `ap-south-1` Mumbai, `us-east-1`, `eu-central-1`). dYdX price/order traffic goes out over the internet from wherever the box is; any region works. Stay in **one** region for everything below.

---

## 2 · Launch the EC2 instance

**EC2 → Instances → Launch an instance.**

| Setting | Value | Notes |
|---|---|---|
| **Name** | `statsarbbot` | |
| **AMI** | **Ubuntu Server 24.04 LTS** (x86_64) | Free-tier eligible base image |
| **Instance type** | **`t3.small`** (2 vCPU / 2 GB) | Minimum that builds the images without OOM. `t3.micro` (free tier, 1 GB) will **fail the `next build` / pip install** unless you add swap (see §3.5). `t3.medium` (4 GB) is comfortable. |
| **Key pair** | **Create new** → `statsarbbot-key` → download the `.pem` | This is your SSH login. Keep the `.pem` safe — you can't re-download it. |
| **Network / Security group** | **Create** with the rules below | This is your firewall |
| **Storage** | **30 GB gp3** | Docker images + the `OhlcvCache` seed + Postgres need room (the prototype once filled an 8 GB disk) |

**Security group inbound rules:**

| Type | Port | Source | Why |
|---|---|---|---|
| SSH | 22 | **My IP** (not `0.0.0.0/0`) | Your admin access only |
| HTTP | 80 | `0.0.0.0/0` | For Let's Encrypt + redirect (TLS step) |
| HTTPS | 443 | `0.0.0.0/0` | The dashboard, once nginx+TLS is set up |
| Custom TCP | 3000 | **My IP** | **Quick-start only** — temporary, to reach the UI before TLS. Remove after §9. |

**Do NOT open 8000 (API) or 5432 (Postgres).** They stay private; only containers and the host (via localhost) use them. Launch the instance.

---

## 3 · Stable address + connect

### 3.1 Elastic IP (so the address survives stop/start)
**EC2 → Elastic IPs → Allocate** → then **Actions → Associate** to your instance. Note the IP — call it `<EIP>` below. (Without this, stopping the instance changes its public IP.)

### 3.2 SSH in
On your laptop:
```bash
chmod 400 ~/Downloads/statsarbbot-key.pem
ssh -i ~/Downloads/statsarbbot-key.pem ubuntu@<EIP>
```
You're now on the server (prompt shows `ubuntu@...`). Everything below runs **on the instance** unless it says "on your laptop."

### 3.5 (t3.micro only) Add swap so builds don't OOM
Skip on `t3.small`+. On a 1 GB box, give Docker breathing room:
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 4 · Install Docker + Compose

```bash
sudo apt update && sudo apt upgrade -y
# Docker Engine + Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu          # run docker without sudo
newgrp docker                            # apply the group now (or log out/in)
docker --version && docker compose version
```

---

## 5 · Get the code onto the instance

The repo is private, so cloning needs a credential. Easiest: a **GitHub Personal Access Token (classic)** with `repo` scope (create at github.com → Settings → Developer settings → Tokens).

```bash
git clone https://<YOUR_GH_USERNAME>:<YOUR_TOKEN>@github.com/sauravs/statsArbBot.git
cd statsArbBot
```
(Alternatively: add a read-only **deploy key** to the repo and clone over SSH. Don't paste the token into shell history on a shared box — use `git clone` interactively if unsure.)

---

## 6 · Configure secrets (`.env`)

```bash
cp .env.example .env
nano .env          # fill in the values below, then Ctrl-O, Enter, Ctrl-X
chmod 600 .env     # owner-only
```

Fill these for a **testnet** deploy (full list is in `.env.example`):

| Variable | Set to | Notes |
|---|---|---|
| `ENVIRONMENT` | `testnet` | Keep testnet until §11. |
| `POSTGRES_PASSWORD` | a strong random string | Compose builds `DATABASE_URL` from this automatically. |
| `DASHBOARD_PASSWORD` | your 6-digit (or longer) login passcode | ⚠️ **Also doubles as the API key** (`X-API-Key`) the proxy and cron use — see config.py. |
| `DASHBOARD_JWT_SECRET` | a long random string | `openssl rand -hex 32` makes a good one. Signs the session JWT. |
| `DYDX_WALLET_API_KEY` / `DYDX_PRIVATE_KEY` | your **testnet** dYdX creds | Needed only when you actually run live passes; the dashboard/scan/sim work without them. |
| `SCAN_DATA_SOURCE` | `dydx` | Live mainnet indexer for real pairs. Use `fake` if you just want to click around offline. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | leave as placeholders for now | Filling **both** enables the live approval gate; leaving them keeps auto-approve + log alerts. |

> The Compose file already injects `DATABASE_URL` (pointing at the `postgres` service) into the `api` container and passes only `DASHBOARD_PASSWORD`/`DASHBOARD_JWT_SECRET`/`API_URL` into the `ui` container — you don't edit those.

---

## 7 · Launch the stack

```bash
docker compose up -d --build
```
This builds both images and starts all three containers. On first boot the `api` container automatically runs `prisma generate` + `prisma migrate deploy` (applies migrations `0001`–`0008`) before uvicorn starts. The build takes a few minutes (heavier on a small instance).

Check it came up:
```bash
docker compose ps                                  # all three "running"/"healthy"
curl -s http://localhost:8000/health               # public liveness → {"status":"ok",...}
curl -s -H "X-API-Key: $DASHBOARD_PASSWORD" \
     http://localhost:8000/api/system/health        # authed readiness → database: connected
docker compose logs -f api                          # watch startup (Ctrl-C to stop tailing)
```

---

## 8 · Quick-start access (no TLS yet)

Open **`http://<EIP>:3000`** in your browser → the login screen → enter your `DASHBOARD_PASSWORD`. You should land on the dashboard, run a scan, see pairs, etc.

> This is HTTP (unencrypted) and intended only for the initial testnet smoke test. Your passcode travels in the clear — fine on your own IP for a few minutes, not for ongoing use. Do §9 next.

---

## 9 · Production access: nginx + HTTPS (recommended)

Serve the dashboard over TLS on `443` and stop exposing `3000`.

**9.1 — (Recommended) Point a domain at `<EIP>`.** Add an `A` record `bot.example.com → <EIP>` at your DNS provider. (You can skip the domain and use a self-signed cert, but Let's Encrypt needs a real hostname.)

**9.2 — Install nginx + certbot on the host** (outside Docker):
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

**9.3 — Reverse-proxy to the UI container** (which maps to `127.0.0.1:3000`). Create `/etc/nginx/sites-available/statsarbbot`:
```nginx
server {
    server_name bot.example.com;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/statsarbbot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d bot.example.com      # provisions + auto-renews TLS
```

**9.4 — Close the temporary hole.** In the EC2 Security Group, **delete the port `3000` rule**. The UI is now reachable only via `https://bot.example.com`.

---

## 10 · Driving live trading passes (cron)

Live **entry/exit are explicit API calls** (the testable seam that replaced the prototype's cron flags; the in-process APScheduler already drives real-time-sim ticks — no cron needed for sims). On the host, a cron job hits the API through localhost, sending the shared key:

```bash
sudo mkdir -p /var/log/statsarb
sudo tee /etc/cron.d/statsarb >/dev/null <<'CRON'
# Drive live passes. KEY must equal DASHBOARD_PASSWORD (the X-API-Key).
*/15 * * * * ubuntu KEY=$(grep '^DASHBOARD_PASSWORD=' /home/ubuntu/statsArbBot/.env | cut -d= -f2-); curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8000/api/live/entry-scan  >> /var/log/statsarb/pass.log 2>&1
*/5  * * * * ubuntu KEY=$(grep '^DASHBOARD_PASSWORD=' /home/ubuntu/statsArbBot/.env | cut -d= -f2-); curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8000/api/live/exit-manage >> /var/log/statsarb/pass.log 2>&1
CRON
```
Cadence is your call — entry less often, exit more often so positions are managed promptly. The exit pass also reconciles/orphan-closes, so keep it running even when the bot is deactivated. **Only enable this once you've activated a live session from the dashboard and rotated to real creds (testnet first).**

---

## 11 · Before mainnet (real money)

Do **all** of this before setting `ENVIRONMENT=mainnet` and restarting (`docker compose up -d`). This mirrors `DEPLOYMENT.md` §7:

1. **Rotate every secret** out of the dev `.env`: fresh dYdX **mainnet** wallet key, a new Telegram bot token, a strong `DASHBOARD_PASSWORD`, a long random `DASHBOARD_JWT_SECRET`. Remove the unused `EXA_API_KEY` leftover if present.
2. **Validate on testnet first:** run a full `forward_test` cycle — confirm an entry opens a real testnet position, exit/stop closes it, P&L records correctly. This closes the Phase-5a live-order gate the automated suite (all fakes) can't.
3. **Fix [issue #16](https://github.com/sauravs/statsArbBot/issues/16)** (resync `wallet.sequence` after a failed dYdX broadcast) — it lives in the never-executed live order path and blocks reliable live trading.
4. **Enable Telegram approval** (set both `TELEGRAM_*`) so live entries/exits need a human ✅; verify the live bot against a real Telegram bot (the polling loop is exercised only by mocks in tests).
5. Confirm the Security Group exposes only `443` (+ `22` from your IP) and `.env` is `600`.
6. Use a **paid, reliable instance** (don't run mainnet on a free-tier/spot box — an outage with an open position is a money bug).

---

## 12 · Day-2 operations

| Task | Command (on the instance, in `~/statsArbBot`) |
|---|---|
| **Logs** | `docker compose logs -f api` / `... ui` / `... postgres`; cron at `/var/log/statsarb/pass.log` |
| **Restart** | `docker compose restart` (state persists in the volume) |
| **Upgrade to new code** | `git pull` → `docker compose up -d --build` (migrations auto-apply on api start) |
| **DB backup** | `docker compose exec postgres pg_dump -U statsarb statsarb > backup_$(date +%F).sql` |
| **DB restore** | `cat backup.sql \| docker compose exec -T postgres psql -U statsarb statsarb` |
| **Seed OhlcvCache** (for backtest/FF) | `docker compose exec api python scripts/ingest_historical.py` |
| **Stop to save cost** | `docker compose down` (keeps the volume) then optionally stop the EC2 instance |
| **Wipe everything** | `docker compose down -v` ⚠️ deletes the Postgres volume |
| **Free disk** | `docker system prune -f` (the prototype once filled the disk — keep an eye on `df -h`) |

**Cost (rough, on-demand):** `t3.small` ≈ $15/mo + 30 GB gp3 ≈ $2.4/mo + Elastic IP (free while attached to a running instance). Stop the instance when not validating to pause compute charges. The first 12 months include free-tier hours if you used `t3.micro`.

---

## 13 · Troubleshooting

- **Build killed / OOM on `next build` or pip install** → instance too small. Use `t3.small`+ or add swap (§3.5).
- **`prisma` errors / `FieldNotFound`** → the `api` container regenerates the client on every start; `docker compose up -d --build` after a schema change. Check `docker compose logs api`.
- **Browser can't reach `:3000`** → Security Group rule missing/removed, or the `ui` container isn't up (`docker compose ps`).
- **`database: connected` fails on `/api/system/health`** → Postgres still starting (it has a healthcheck; the api waits) or `POSTGRES_PASSWORD` mismatch — check `docker compose logs postgres`.
- **Disk full** → `docker system prune -f`; check `df -h` and the 30 GB sizing.
- **Locked out via SSH** → your home IP changed; update the SG port-22 source to your new IP in the EC2 console.

---

*This is a runbook; nothing here has been executed against AWS. Validate the whole flow on testnet before mainnet, and read `DEPLOYMENT.md` for the architecture rationale and the non-Docker (venv+systemd) alternative.*
