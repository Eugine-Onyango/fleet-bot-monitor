#!/bin/bash
set -e

echo "============================================================"
echo "🚀 ULTRA-LIGHT 3-PROCESS ENGINE • FRESH CLEAN START (108 BOTS)"
echo "   • RAM Usage: ~40 MB total for all 108 bots (3 Python processes)"
echo "   • Cooldown:  30-Minute Rest per bot (1800s)"
echo "   • Fleets:    6 Helper Bots per Team (Trades occur every 5 minutes)"
echo "   ------------------------------------------------------------"
echo "   • Account 1 (DOT91203477): 36 E/O Bots (Lock Recovery)   -> CLEAN START"
echo "   • Account 2 (DOT93845070): 36 E/O Bots (Switch Recovery) -> CLEAN START"
echo "   • Account 3 (DOT91362122): 36 C/P Bots (Switch Recovery) -> CLEAN START"
echo "   • Bybit Fleet (Crypto):    6 Bots                        -> 100% UNTOUCHED"
echo "============================================================"

# Ensure extra 1GB swap is active so the VPS runs cool and smooth
if ! swapon --show | grep -q "/swapfile_extra"; then
  echo "⚡ Ensuring 1GB swap (/swapfile_extra) is active..."
  fallocate -l 1G /swapfile_extra 2>/dev/null || dd if=/dev/zero of=/swapfile_extra bs=1M count=1024 status=none
  chmod 600 /swapfile_extra
  mkswap /swapfile_extra >/dev/null 2>&1 || true
  swapon /swapfile_extra 2>/dev/null || true
fi

# ------------------------------------------------------------
# 1. STOP & CLEAN PREVIOUS CONTAINERS / PROCESSES (BYBIT UNTOUCHED)
# ------------------------------------------------------------
echo "🛑 Stopping and cleaning old bot containers (Bybit preserved)..."
docker ps -aq --filter "name=my-even-odd" --filter "name=my-over-under" --filter "name=my-call-put" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker rm -f acc1-fleet-runner acc2-fleet-runner acc3-fleet-runner >/dev/null 2>&1 || true

pkill -f "run_acc1_fleet" 2>/dev/null || true
pkill -f "run_acc2_fleet" 2>/dev/null || true
pkill -f "run_acc3_fleet" 2>/dev/null || true
pkill -f "even_odd_millipede.py" 2>/dev/null || true
pkill -f "call_put_fleet.py" 2>/dev/null || true

# ------------------------------------------------------------
# 2. WIPE ALL DERIV STATE FILES & LOGS (RESET EVERYTHING TO $0.00)
# ------------------------------------------------------------
echo "🧹 Wiping all old state files & logs for a 100% clean start..."
rm -rf /root/even_odd_millipede_bot_* /root/even_odd_fleet2_bot_* /root/even_odd_fleet3_bot_* 2>/dev/null || true
rm -rf /root/over_under_fleet_bot_* /root/over_under_fleet2_bot_* /root/over_under_fleet3_bot_* 2>/dev/null || true
rm -rf /root/call_put_fleet_bot_* /root/call_put_fleet2_bot_* 2>/dev/null || true
rm -rf /root/acc2_* /root/acc3_* 2>/dev/null || true

# ------------------------------------------------------------
# 3. RE-INITIALIZE TRADE LOCKS
# ------------------------------------------------------------
MASTER_LOCK_ACC1="/root/shared_master_trade_lock"
MASTER_LOCK_ACC2="/root/shared_master_trade_lock_acc2"
MASTER_LOCK_ACC3="/root/shared_master_trade_lock_acc3"
mkdir -p "$MASTER_LOCK_ACC1" "$MASTER_LOCK_ACC2" "$MASTER_LOCK_ACC3"
rm -rf "$MASTER_LOCK_ACC1/trade_lock" "$MASTER_LOCK_ACC1/lock_info.json"
rm -rf "$MASTER_LOCK_ACC2/trade_lock" "$MASTER_LOCK_ACC2/lock_info.json"
rm -rf "$MASTER_LOCK_ACC3/trade_lock" "$MASTER_LOCK_ACC3/lock_info.json"

# ------------------------------------------------------------
# 4. RESET HISTORICAL PEAK PROFITS (WIPE DERIV PEAKS TO $0.00, KEEP BYBIT)
# ------------------------------------------------------------
echo "🎯 Resetting historical Deriv peak profits completely to \$0.00..."
python3 -c "
import json, os
bybit_peak = 0.0
if os.path.exists('/root/fleet_peak_profits.json'):
  try:
    with open('/root/fleet_peak_profits.json', 'r') as f:
      old = json.load(f)
      bybit_peak = float(old.get('systems', {}).get('bybit', 0.0))
  except Exception:
    pass

d = {
  'overall': bybit_peak,
  'reset_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'systems': {'eo': 0.0, 'ou': 0.0, 'cp': 0.0, 'bybit': bybit_peak},
  'account_systems': {
    'acc1_eo': 0.0, 'acc1_ou': 0.0, 'acc1_cp': 0.0, 'acc1_all': 0.0,
    'acc2_eo': 0.0, 'acc2_ou': 0.0, 'acc2_cp': 0.0, 'acc2_all': 0.0,
    'acc3_eo': 0.0, 'acc3_ou': 0.0, 'acc3_cp': 0.0, 'acc3_all': 0.0
  },
  'account_fleets': {},
  'fleets': {},
  'bots': {}
}
with open('/root/fleet_peak_profits.json', 'w') as f:
  json.dump(d, f, indent=2)
" 2>/dev/null || true

# ------------------------------------------------------------
# 5. PULL LATEST BOT CODE & CONFIGS (30m Cooldown + Single-Process Scheduler)
# ------------------------------------------------------------
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"
EO_BUILD="/root/eo_fleet_build"
CP_BUILD="/root/cp_fleet_build"
mkdir -p "$EO_BUILD" "$CP_BUILD"

curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > "$EO_BUILD/even_odd_millipede.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > "$EO_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/Dockerfile" > "$EO_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/requirements.txt" > "$EO_BUILD/requirements.txt"
cd "$EO_BUILD"
docker build -q -t headless-even-odd-millipede . >/dev/null

curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/call_put_fleet.py" > "$CP_BUILD/call_put_fleet.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/config.json" > "$CP_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/Dockerfile" > "$CP_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/requirements.txt" > "$CP_BUILD/requirements.txt"
cd "$CP_BUILD"
docker build -q -t headless-call-put-fleet . >/dev/null

# ------------------------------------------------------------
# 6. LAUNCH ACCOUNT 1 (1 PYTHON PROCESS MANAGING ALL 36 BOTS)
# ------------------------------------------------------------
echo "🚀 Launching Account 1 (36 Bots in 1 Ultra-Light Process • Lock Recovery)..."
cat << 'EOF' > /root/run_acc1_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT91203477"
export DERIV_API_TOKEN="pat_d858bf2ec8a6a47d45bfa2d4a7182ce7e63d993912dacfe4a5af32266af07277"
export SWITCH_MARKET_ON_LOSS="false"
export LOCK_DIR="/root/shared_master_trade_lock"

for d_prefix in even_odd_millipede_bot even_odd_fleet2_bot over_under_fleet_bot over_under_fleet2_bot over_under_fleet3_bot even_odd_fleet3_bot; do
  for i in 1 2 3 4 5 6; do
    mkdir -p "/root/${d_prefix}_$i"
    cp /root/eo_fleet_build/config.json "/root/${d_prefix}_$i/config.json"
  done
done

while true; do
  python3 -u /root/eo_fleet_build/even_odd_millipede.py --multi-scheduler acc1
  sleep 5
done
EOF
chmod +x /root/run_acc1_fleet.sh

docker run -d --restart always --name acc1-fleet-runner \
  --pid=host \
  -v /root:/root \
  --entrypoint /bin/bash \
  headless-even-odd-millipede /root/run_acc1_fleet.sh >/dev/null
echo "✅ Account 1: 36 Bots active in 1 single Python process (~13 MB RAM)."

# ------------------------------------------------------------
# 7. LAUNCH ACCOUNT 2 (1 PYTHON PROCESS MANAGING ALL 36 BOTS)
# ------------------------------------------------------------
echo "🚀 Launching Account 2 (36 Bots in 1 Ultra-Light Process • Switch Recovery)..."
cat << 'EOF' > /root/run_acc2_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT93845070"
export DERIV_API_TOKEN="pat_e8b31d27beb9c0a040f1059ce12bac092383a3838554078c75378bf9831bf955"
export SWITCH_MARKET_ON_LOSS="true"
export LOCK_DIR="/root/shared_master_trade_lock_acc2"

for d_prefix in even_odd_millipede_bot even_odd_fleet2_bot over_under_fleet_bot over_under_fleet2_bot over_under_fleet3_bot even_odd_fleet3_bot; do
  for i in 1 2 3 4 5 6; do
    mkdir -p "/root/acc2_${d_prefix}_$i"
    cp /root/eo_fleet_build/config.json "/root/acc2_${d_prefix}_$i/config.json"
  done
done

while true; do
  python3 -u /root/eo_fleet_build/even_odd_millipede.py --multi-scheduler acc2
  sleep 5
done
EOF
chmod +x /root/run_acc2_fleet.sh

docker run -d --restart always --name acc2-fleet-runner \
  --pid=host \
  -v /root:/root \
  --entrypoint /bin/bash \
  headless-even-odd-millipede /root/run_acc2_fleet.sh >/dev/null
echo "✅ Account 2: 36 Bots active in 1 single Python process (~13 MB RAM)."

# ------------------------------------------------------------
# 8. LAUNCH ACCOUNT 3 (1 PYTHON PROCESS MANAGING ALL 36 BOTS)
# ------------------------------------------------------------
echo "🚀 Launching Account 3 (36 Bots in 1 Ultra-Light Process • Call/Put Switch)..."
cat << 'EOF' > /root/run_acc3_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT91362122"
export DERIV_API_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"
export SWITCH_MARKET_ON_LOSS="true"
export LOCK_DIR="/root/shared_master_trade_lock_acc3"

for d_prefix in even_odd_millipede_bot even_odd_fleet2_bot over_under_fleet_bot over_under_fleet2_bot over_under_fleet3_bot even_odd_fleet3_bot; do
  for i in 1 2 3 4 5 6; do
    mkdir -p "/root/acc3_${d_prefix}_$i"
    cp /root/cp_fleet_build/config.json "/root/acc3_${d_prefix}_$i/config.json"
  done
done

while true; do
  python3 -u /root/cp_fleet_build/call_put_fleet.py --multi-scheduler acc3
  sleep 5
done
EOF
chmod +x /root/run_acc3_fleet.sh

docker run -d --restart always --name acc3-fleet-runner \
  --pid=host \
  -v /root:/root \
  --entrypoint /bin/bash \
  headless-call-put-fleet /root/run_acc3_fleet.sh >/dev/null
echo "✅ Account 3: 36 Bots active in 1 single Python process (~13 MB RAM)."

# ------------------------------------------------------------
# 9. UPDATE AND RESTART MONITOR PUSHER
# ------------------------------------------------------------
echo "🔄 Updating & restarting live monitor pusher..."
EXISTING_TOKEN=$(grep -oP 'GITHUB_TOKEN = os\.getenv\("GITHUB_TOKEN", "\K[^"]+' /root/fleet_monitor_pusher.py 2>/dev/null || true)
EXISTING_GIST=$(grep -oP 'GIST_ID = os\.getenv\("GIST_ID", "\K[^"]+' /root/fleet_monitor_pusher.py 2>/dev/null || true)
pkill -f fleet_monitor_pusher.py 2>/dev/null || true
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/fleet_monitor_pusher.py" > /root/fleet_monitor_pusher.py
if [ -n "$EXISTING_TOKEN" ] && [ "$EXISTING_TOKEN" != "YOUR_GITHUB_TOKEN_HERE" ]; then
  sed -i "s/YOUR_GITHUB_TOKEN_HERE/$EXISTING_TOKEN/g" /root/fleet_monitor_pusher.py
fi
if [ -n "$EXISTING_GIST" ]; then
  sed -i "s/e89e6db2da1433214922b69f101e15aa/$EXISTING_GIST/g" /root/fleet_monitor_pusher.py
fi
if [ -f /root/run_pusher.sh ]; then
  /root/run_pusher.sh
else
  nohup python3 -u /root/fleet_monitor_pusher.py > /root/pusher.log 2>&1 &
fi

sleep 4
echo ""
echo "============================================================"
echo "🎉 ULTRA-LIGHT 3-PROCESS ENGINE DEPLOYED (108 BOTS • ~40MB RAM)!"
echo "   • Account 1 (DOT91203477): 36 E/O Bots (Lock Recovery)   - LIVE (1 Process)"
echo "   • Account 2 (DOT93845070): 36 E/O Bots (Switch Recovery) - LIVE (1 Process)"
echo "   • Account 3 (DOT91362122): 36 C/P Bots (Switch Recovery) - LIVE (1 Process)"
echo "   • Bybit Fleet:             6 Crypto Bots                 - 100% UNTOUCHED"
echo "   • Dashboard Live at:       https://fleet-bot-monitor.vercel.app"
echo "============================================================"
free -h
