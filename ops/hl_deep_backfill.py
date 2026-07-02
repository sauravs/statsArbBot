#!/usr/bin/env python3
"""
Hyperliquid DEEP historical backfill from the S3 archive `asset_ctxs` dataset.

asset_ctxs/YYYYMMDD.csv.lz4 holds per-coin, per-MINUTE snapshots with columns:
  time, coin, funding, open_interest, prev_day_px, day_ntl_vlm, premium,
  oracle_px, mark_px, mid_px, impact_bid_px, impact_ask_px
We aggregate `mid_px` into hourly OHLC (open=first min, high/low, close=last min),
carry `day_ntl_vlm` as a liquidity/volume proxy (the archive has no trades feed),
and sample `funding` hourly. Rows are UPSERTed into ohlcv_cache / funding_rate_cache
(exchange=hyperliquid, resolution=1HOUR) — non-destructive (ON CONFLICT DO UPDATE),
per (exchange,market,resolution,timestamp). Resumable via a done-file.

Runs ON the EC2 box (needs: aws cli w/ instance role, lz4, docker compose postgres).
Same-region S3 -> EC2 transfer is free; requester-pays adds only trivial request cost.

Modes:
  --validate S E   aggregate [S,E], compare sentinel hourly closes vs the closes
                   already in the DB (the live-based bars); print % diff; NO writes.
  --run S E        aggregate + upsert each day in [S,E]; resumable.
Dates are YYYYMMDD. Defaults: run 20240101..20251204 (the gap; leaves live recent bars).
"""
import argparse, csv, datetime as dt, hashlib, os, subprocess, sys

BUCKET = "s3://hyperliquid-archive"
RP = ["--request-payer", "requester"]
WORK = "/tmp/hl_deep"
DONE_FILE = os.environ.get("HL_DONE_FILE", os.path.expanduser("~/hl_deep_backfill.done"))
REPO = os.environ.get("STATSARB_REPO", os.path.expanduser("~/statsArbBot"))
SENTINELS = ["BTC", "ETH", "SOL"]

TARGETS = set("""
0G 2Z AAVE ACE ADA AERO AIXBT ALGO ALT ANIME APE APEX APT AR ARB ARK ASTER ATOM AVAX AVNT AXS AZTEC BABY
BANANA BCH BERA BIGTIME BIO BLUR BNB BOME BRETT BSV BTC CAKE CC CELO CFX CHIP COMP CRV DASH DOGE DOOD DOT
DYDX DYM EIGEN ENA ENS ETC ETH ETHFI FARTCOIN FET FIL FOGO GALA GAS GMT GMX GOAT GRASS GRIFFAIN HBAR HEMI
HMSTR HYPE HYPER ICP IMX INIT INJ IO IOTA IP JTO JUP KAITO KAS LAYER LDO LINEA LINK LIT LTC MANTA ME MEGA
MELANIA MEME MERL MET MINA MNT MON MOODENG MORPHO MOVE NEAR NEO NIL NOT NXPC ONDO OP ORDI PAXG PENDLE PENGU
PEOPLE PNUT POL POLYX POPCAT PROVE PUMP PURR PYTH RENDER RESOLV REZ RSR RUNE S SAGA SAND SEI SKR SKY SNX SOL
SOPH SPX STABLE STBL STRK STX SUI SUPER SUSHI SYRUP TAO TIA TNSR TON TRB TRUMP TRX TURBO UMA UNI USUAL VINE
VIRTUAL VVV W WCT WIF WLD WLFI XAI XLM XMR XPL XRP YGG ZEC ZEN ZETA ZK ZORA ZRO kBONK kFLOKI kLUNC kNEIRO
kPEPE kSHIB
""".split())


def log(m): print(m, flush=True)


def psql(sql, capture=True):
    """Run SQL in the postgres container. Returns stdout (text)."""
    cmd = ["docker", "compose", "exec", "-T", "postgres",
           "psql", "-U", "statsarb", "-d", "statsarb", "-v", "ON_ERROR_STOP=1",
           "-t", "-A", "-F", ",", "-f", "-"]
    r = subprocess.run(cmd, input=sql, text=True, capture_output=True, cwd=REPO)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()[:400]}")
    return r.stdout if capture else ""


def fetch_day_csv(ymd):
    os.makedirs(WORK, exist_ok=True)
    lz = f"{WORK}/{ymd}.csv.lz4"; out = f"{WORK}/{ymd}.csv"
    r = subprocess.run(["aws", "s3", "cp", f"{BUCKET}/asset_ctxs/{ymd}.csv.lz4", lz] + RP,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None  # missing day / transient error
    subprocess.run(["lz4", "-d", "-f", lz, out], capture_output=True)
    try: os.remove(lz)
    except OSError: pass
    return out


def aggregate(csvf, markets):
    """(market, 'YYYY-MM-DDTHH') -> [open, high, low, close, vol, funding]  (rows are time-ordered)."""
    agg = {}
    with open(csvf, newline="") as f:
        for row in csv.DictReader(f):
            coin = row.get("coin")
            if coin not in markets:
                continue
            try:
                mid = float(row["mid_px"])
            except (TypeError, ValueError, KeyError):
                continue
            hour = row["time"][:13]  # YYYY-MM-DDTHH
            try: vol = float(row.get("day_ntl_vlm") or 0)
            except ValueError: vol = 0.0
            try: fund = float(row.get("funding") or 0)
            except ValueError: fund = 0.0
            k = (coin, hour)
            e = agg.get(k)
            if e is None:
                agg[k] = [mid, mid, mid, mid, vol, fund]
            else:
                if mid > e[1]: e[1] = mid
                if mid < e[2]: e[2] = mid
                e[3] = mid; e[4] = vol; e[5] = fund
    return agg


def _ts(hour):  # 'YYYY-MM-DDTHH' -> '2024-01-01T05:00:00+00:00'
    return hour + ":00:00+00:00"


def _mid(exchange, market, resolution, ts):
    return hashlib.md5(f"{exchange}|{market}|{resolution}|{ts}".encode()).hexdigest()


def upsert_day(agg):
    if not agg:
        return 0
    ohlcv_vals, fund_vals = [], []
    for (m, hour), (o, h, l, c, v, fund) in agg.items():
        ts = _ts(hour)
        oid = _mid("hyperliquid", m, "1HOUR", ts)
        ohlcv_vals.append(f"('{oid}','hyperliquid','{m}','1HOUR','{ts}',{o},{h},{l},{c},{v})")
        fid = hashlib.md5(f"hyperliquid|{m}|{ts}".encode()).hexdigest()
        fund_vals.append(f"('{fid}','hyperliquid','{m}','{ts}',{fund})")
    sql = ["BEGIN;"]
    for i in range(0, len(ohlcv_vals), 2000):
        chunk = ",".join(ohlcv_vals[i:i+2000])
        sql.append(
            "INSERT INTO ohlcv_cache (id,exchange,market,resolution,timestamp,open,high,low,close,volume) VALUES "
            + chunk +
            " ON CONFLICT (exchange,market,resolution,timestamp) DO UPDATE SET "
            "open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume;")
    for i in range(0, len(fund_vals), 2000):
        chunk = ",".join(fund_vals[i:i+2000])
        sql.append(
            "INSERT INTO funding_rate_cache (id,exchange,market,timestamp,funding_rate) VALUES "
            + chunk +
            " ON CONFLICT (exchange,market,timestamp) DO UPDATE SET funding_rate=EXCLUDED.funding_rate;")
    sql.append("COMMIT;")
    psql("\n".join(sql), capture=False)
    return len(ohlcv_vals)


def load_done():
    if not os.path.exists(DONE_FILE):
        return set()
    with open(DONE_FILE) as f:
        return set(x.strip() for x in f if x.strip())


def mark_done(ymd):
    with open(DONE_FILE, "a") as f:
        f.write(ymd + "\n"); f.flush()


def daterange(s, e):
    d = s
    while d <= e:
        yield d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)


def cmd_run(s, e):
    done = load_done()
    dates = [d for d in daterange(s, e) if d not in done]
    log(f"[run] {len(dates)} days to process ({s:%Y%m%d}..{e:%Y%m%d}); {len(done)} already done")
    ok = 0
    for ymd in dates:
        try:
            csvf = fetch_day_csv(ymd)
            if csvf is None:
                log(f"  {ymd}: no archive file (skip, marking done)"); mark_done(ymd); continue
            agg = aggregate(csvf, TARGETS)
            n = upsert_day(agg)
            os.remove(csvf)
            mark_done(ymd); ok += 1
            if ok % 20 == 0 or n == 0:
                log(f"  {ymd}: upserted {n} hourly rows  ({ok}/{len(dates)})")
        except Exception as ex:
            log(f"  {ymd}: ERROR {type(ex).__name__}: {str(ex)[:200]} (left undone; will retry)")
    remaining = [d for d in daterange(s, e) if d not in load_done()]
    log(f"[run] pass complete: {len(remaining)} days still remaining")
    return 0 if not remaining else 1


def cmd_validate(s, e):
    log(f"[validate] aggregating {s:%Y%m%d}..{e:%Y%m%d} (sentinels {SENTINELS}); NO writes")
    merged = {}
    for ymd in daterange(s, e):
        csvf = fetch_day_csv(ymd)
        if csvf is None:
            log(f"  {ymd}: no archive file"); continue
        merged.update(aggregate(csvf, set(SENTINELS)))
        os.remove(csvf)
    # compare our close vs DB's existing (live-based) close, per sentinel
    for mkt in SENTINELS:
        rows = {h: c for (m, h), (o, hi, lo, c, v, f) in merged.items() if m == mkt}
        if not rows:
            log(f"  {mkt}: no archive rows"); continue
        lo_ts = _ts(min(rows)); hi_ts = _ts(max(rows))
        out = psql(f"SELECT to_char(timestamp,'YYYY-MM-DD\"T\"HH24'), close FROM ohlcv_cache "
                   f"WHERE exchange='hyperliquid' AND market='{mkt}' AND resolution='1HOUR' "
                   f"AND timestamp>='{lo_ts}' AND timestamp<='{hi_ts}';")
        db = {}
        for line in out.splitlines():
            if "," in line:
                h, c = line.rsplit(",", 1)
                try: db[h] = float(c)
                except ValueError: pass
        common = [h for h in rows if h in db]
        if not common:
            log(f"  {mkt}: {len(rows)} archive hrs, but 0 overlap with DB (live bars absent here)"); continue
        diffs = [abs(rows[h] - db[h]) / db[h] for h in common if db[h]]
        mean = sum(diffs) / len(diffs) * 100
        mx = max(diffs) * 100
        log(f"  {mkt}: {len(common)} overlapping hrs | mean |Δclose|={mean:.4f}%  max={mx:.4f}%")


def main():
    os.chdir(REPO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", nargs=2, metavar=("S", "E"))
    ap.add_argument("--run", nargs=2, metavar=("S", "E"))
    a = ap.parse_args()
    fmt = lambda x: dt.datetime.strptime(x, "%Y%m%d")
    if a.validate:
        cmd_validate(fmt(a.validate[0]), fmt(a.validate[1])); return 0
    s, e = (a.run if a.run else ("20240101", "20251204"))
    return cmd_run(fmt(s), fmt(e))


if __name__ == "__main__":
    sys.exit(main())
