#!/usr/bin/env bash
# Rolling, non-destructive top-up of the OHLCV+funding cache for one exchange,
# via the local /api/data/fetch endpoint (window/exchange/market-scoped merge —
# never deletes outside the window, never touches other exchanges).
# Usage: topup.sh <dydx|hyperliquid> [days]   (default 12-day rolling window)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1          # -> ~/statsArbBot
EX="${1:?exchange required}"; DAYS="${2:-12}"
LOG="$(dirname "$0")/topup.log"

# keep the log small (last ~1 MB)
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then
  tail -c 1000000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

KEY=$(grep -E '^(DASHBOARD_PASSWORD|API_KEY)=' .env | head -1 | cut -d= -f2- | tr -d '"')
END=$(date -u +%Y-%m-%dT%H:00:00+00:00)
START=$(date -u -d "$DAYS days ago" +%Y-%m-%dT00:00:00+00:00)
RESP=$(curl -s -m 30 -X POST http://127.0.0.1:8000/api/data/fetch \
  -H "x-api-key: $KEY" -H 'content-type: application/json' \
  -d "{\"start\":\"$START\",\"end\":\"$END\",\"exchange\":\"$EX\"}" 2>&1)
echo "$(date -u +%FT%TZ) topup $EX ${START}..${END} -> ${RESP:0:200}" >> "$LOG"
