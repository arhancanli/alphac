#!/bin/zsh
# Bootstrap a Binance-reachable VPS as the crypto sleeve's DATA INGEST host.
#
#   ./scripts/vps_crypto_bootstrap.sh <ip> [ssh_key]
#
# WHY A SECOND HOST EXISTS AT ALL
# --------------------------------
# AlphaForge (crypto funding carry) is one of four sleeves and has ~27% lifetime uptime because
# Binance is unreachable from every machine we own, for two DIFFERENT reasons, both measured
# 2026-08-10:
#   * the Mac (currently Turkey): fapi.binance.com returns HTTP 000 in 0.03s — an instant
#     connection reset. Bybit, OKX and Kraken fail identically, so this is a network-layer block
#     on exchange endpoints, not a Binance decision and not DNS (DNS resolves, TCP 443 connects).
#   * the existing MoonShot VPS (US): HTTP 451 "Service unavailable from a restricted location" —
#     Binance geo-blocks US IPs. That VPS can NEVER be the fix, whatever we install on it.
# So the fix is a host in a jurisdiction Binance actually serves. That is the ONLY thing this new
# host is for.
#
# WHAT THIS HOST DOES AND DELIBERATELY DOES NOT DO
# ------------------------------------------------
# DOES : pull Binance funding + OHLCV into a local lake, on a timer, and let the Mac rsync it down.
# DOES NOT: trade, hold broker credentials, compute published state, or hold the transparency
#           signing key. Trading stays on the Mac because Alpaca is reachable from Turkey (verified
#           — AlphaVintage submitted successfully 2026-08-10). Splitting the signed transparency
#           chain across two hosts would create two writers to an append-only record, which is an
#           integrity risk far worse than the data staleness we are fixing.
#
# FAILS CLOSED ON THE WRONG REGION. Step 1 verifies Binance actually answers from this host and
# ABORTS if it does not. Provisioning in the wrong region is the single likeliest way to waste
# money here, so it is checked before anything is installed.

set -u
IP="${1:-}"
KEY="${2:-$HOME/.ssh/moonshot_vps}"
if [ -z "$IP" ]; then echo "usage: $0 <ip> [ssh_key]"; exit 2; fi

# ARRAY, NOT A STRING — and this is not style, it is a bug this script already had.
# zsh does NOT word-split unquoted parameters the way bash does, so `SSH="ssh -i k host"` followed
# by `"${SSH[@]}" 'cmd'` makes zsh look for a single executable literally named "ssh -i k host", which
# fails with "no such file or directory". On 2026-08-10 that made STEP 1 report
# "fapi.binance.com/ping -> HTTP <no answer>" and abort — reading as "Binance is blocked in
# Frankfurt" when in truth the ssh command had never run. Binance answered HTTP 200 from that host.
# A guard that fails closed is right; a guard that fails closed for the WRONG REASON sends you to
# re-provision in another region for nothing. Arrays expand element-wise in zsh and cannot do this.
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 root@"$IP")

echo "=============================================================================="
echo " STEP 1 — VERIFY BINANCE IS REACHABLE FROM $IP  (abort if not)"
echo "=============================================================================="
CODE=$("${SSH[@]}" 'curl -s -o /dev/null -w "%{http_code}" --max-time 15 https://fapi.binance.com/fapi/v1/ping' 2>/dev/null)
echo "  fapi.binance.com/ping -> HTTP ${CODE:-<no answer>}"
case "$CODE" in
  200) echo "  OK — Binance serves this location." ;;
  451) echo "  ABORT: HTTP 451 = geo-blocked (same failure as the US VPS). Destroy this droplet and"
       echo "         re-provision in Frankfurt / Amsterdam / Singapore. Nothing was installed."; exit 1 ;;
  *)   echo "  ABORT: unexpected/no response. Not installing onto a host that cannot reach the venue."; exit 1 ;;
esac
"${SSH[@]}" 'curl -s --max-time 15 "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"' | head -c 200; echo

echo
echo "=============================================================================="
echo " STEP 2 — SYSTEM PACKAGES"
echo "=============================================================================="
"${SSH[@]}" 'set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3.12-venv python3-pip rsync git curl >/dev/null
  mkdir -p /opt/alphaforge/{data,var/log,var/locks}
  python3 -V'

echo
echo "=============================================================================="
echo " STEP 3 — SHIP CODE (no data, no credentials, no signing key)"
echo "=============================================================================="
# Explicit include list. A blanket copy would sweep up broker .env files and the ed25519
# transparency key, neither of which has any business on an ingest-only box.
rsync -az --delete -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude='__pycache__' --exclude='*.pyc' \
  "$HOME/alphaforge/src" "$HOME/alphaforge/configs" "$HOME/alphaforge/pyproject.toml" \
  root@"$IP":/opt/alphaforge/ && echo "  code synced"

echo
echo "=============================================================================="
echo " STEP 4 — PYTHON ENV"
echo "=============================================================================="
"${SSH[@]}" 'set -e
  cd /opt/alphaforge
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install -e . 2>&1 | tail -3
  ./.venv/bin/python -c "import ccxt, pyarrow, pandas; print(\"  deps ok: ccxt\", ccxt.__version__)"'

echo
echo "=============================================================================="
echo " STEP 5 — INGEST TIMER (hourly, funding + ohlcv, resumable & dedupe-safe)"
echo "=============================================================================="
"${SSH[@]}" 'set -e
cat >/opt/alphaforge/ingest.sh <<'"'"'EOS'"'"'
#!/bin/bash
# Hourly crypto ingest. Resumable and dedupe-safe: crash at any point and the next run resumes
# from the stored watermarks. Bounded so a hung venue call cannot wedge the timer.
cd /opt/alphaforge || exit 1
LOCK=/opt/alphaforge/var/locks/ingest.lock
mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) another run holds the lock"; exit 0; }
trap "rmdir $LOCK 2>/dev/null" EXIT
{
  echo "=== ingest $(date -u +%FT%TZ) ==="
  timeout 3000 ./.venv/bin/af data update 2>&1 | tail -20 \
    || echo "WARN: af data update returned non-zero"
  echo "=== done $(date -u +%FT%TZ) ==="
} >> /opt/alphaforge/var/log/ingest.log 2>&1
EOS
chmod +x /opt/alphaforge/ingest.sh

cat >/etc/systemd/system/af-ingest.service <<EOS
[Unit]
Description=AlphaForge crypto lake ingest
After=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/alphaforge/ingest.sh
EOS

cat >/etc/systemd/system/af-ingest.timer <<EOS
[Unit]
Description=AlphaForge crypto ingest hourly
[Timer]
OnCalendar=*:05
Persistent=true
[Install]
WantedBy=timers.target
EOS

systemctl daemon-reload
systemctl enable --now af-ingest.timer
systemctl list-timers af-ingest.timer --no-pager | head -3'

echo
echo "=============================================================================="
echo " DONE. Next:"
echo "   1) seed the lake:   rsync -az ~/alphaforge/data/lake/{funding,ohlcv} root@$IP:/opt/alphaforge/data/lake/"
echo "   2) pull it back:    scripts/vps_crypto_sync.sh $IP"
echo "   3) the Mac keeps trading, publishing and signing. This host only fetches data."
echo "=============================================================================="
