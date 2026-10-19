#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING ACCOUNT 2 & ACCOUNT 3 FLEETS (LIGHTWEIGHT MULTI-RUNNER)"
echo "   • Account 1 (DOT91203477): 100% UNTOUCHED (Stays LOCKED on market recovery)"
echo "   • Bybit Fleet:             100% UNTOUCHED"
echo "   ------------------------------------------------------------"
echo "   • Account 2 (DOT93845070 - Even/Odd Market-Switch Recovery):"
echo "       - 6 Even/Odd Teams (4 Bots Each = 24 Bots, 20m Rest)"
echo "       - Recovery Mode: SWITCHES to a different market after 2-step loss"
echo "       - Master Lock: /root/shared_master_trade_lock_acc2"
echo "   ------------------------------------------------------------"
echo "   • Account 3 (DOT91362122 - Call/Put Market-Switch Recovery):"
echo "       - 6 Call/Put Teams (4 Bots Each = 24 Bots, 20m Rest)"
echo "       - Recovery Mode: SWITCHES to a different market after 2-step loss"
echo "       - Master Lock: /root/shared_master_trade_lock_acc3"
echo "============================================================"

# 0. Add 1GB extra swapfile immediately so 1GB RAM VPS never freezes or hits OOM
if ! swapon --show | grep -q "/swapfile_extra"; then
  echo "⚡ Adding 1GB extra swap space (/swapfile_extra) to prevent RAM/Swap freeze..."
  fallocate -l 1G /swapfile_extra 2>/dev/null || dd if=/dev/zero of=/swapfile_extra bs=1M count=1024 status=none
  chmod 600 /swapfile_extra
  mkswap /swapfile_extra >/dev/null 2>&1 || true
  swapon /swapfile_extra 2>/dev/null || true
  if ! grep -q "/swapfile_extra" /etc/fstab; then
    echo "/swapfile_extra none swap sw 0 0" >> /etc/fstab
  fi
fi

# 1. Clean ONLY Account 2 & Account 3 containers/processes (DO NOT touch Account 1 or Bybit!)
echo "🧹 Cleaning any previous Account 2 (acc2-*) and Account 3 (acc3-*) containers..."
pkill -f "docker run.*acc2-" 2>/dev/null || true
pkill -f "docker run.*acc3-" 2>/dev/null || true
docker ps -aq --filter "name=acc2-" --filter "name=acc3-" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true

# 2. Wipe ONLY Account 2 & Account 3 state files & logs
echo "✨ Initializing clean state directories for Account 2 & Account 3..."
rm -rf /root/acc2_*_bot_* /root/acc3_*_bot_* 2>/dev/null || true

# Reset Account 2 & Account 3 peak profits while keeping Account 1 & Bybit peaks 100% intact
if [ -f /root/fleet_peak_profits.json ]; then
  python3 -c "
import json
try:
  with open('/root/fleet_peak_profits.json', 'r') as f:
    d = json.load(f)
  acc_sys = d.setdefault('account_systems', {})
  for k in ['acc2_eo', 'acc2_ou', 'acc2_cp', 'acc3_eo', 'acc3_ou', 'acc3_cp']:
    acc_sys[k] = 0.0
  with open('/root/fleet_peak_profits.json', 'w') as f:
    json.dump(d, f, indent=2)
except Exception:
  pass
" 2>/dev/null || true
fi

# 3. Setup independent master trade lock directories for Account 2 and Account 3
MASTER_LOCK_ACC2="/root/shared_master_trade_lock_acc2"
MASTER_LOCK_ACC3="/root/shared_master_trade_lock_acc3"
mkdir -p "$MASTER_LOCK_ACC2" "$MASTER_LOCK_ACC3"
rm -rf "$MASTER_LOCK_ACC2/trade_lock" "$MASTER_LOCK_ACC2/lock_info.json"
rm -rf "$MASTER_LOCK_ACC3/trade_lock" "$MASTER_LOCK_ACC3/lock_info.json"
echo "🔒 Independent Master Locks initialized:"
echo "   • Account 2 Lock: $MASTER_LOCK_ACC2"
echo "   • Account 3 Lock: $MASTER_LOCK_ACC3"

# 4. Fetch latest bot code and build Docker images
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"

echo "🔨 Updating image: headless-even-odd-millipede..."
EO_BUILD="/root/eo_fleet_build"
mkdir -p "$EO_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > "$EO_BUILD/even_odd_millipede.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > "$EO_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/Dockerfile" > "$EO_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/requirements.txt" > "$EO_BUILD/requirements.txt"
cd "$EO_BUILD"
docker build -q -t headless-even-odd-millipede . >/dev/null

echo "🔨 Updating image: headless-call-put-fleet..."
CP_BUILD="/root/cp_fleet_build"
mkdir -p "$CP_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/call_put_fleet.py" > "$CP_BUILD/call_put_fleet.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/config.json" > "$CP_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/Dockerfile" > "$CP_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/requirements.txt" > "$CP_BUILD/requirements.txt"
cd "$CP_BUILD"
docker build -q -t headless-call-put-fleet . >/dev/null

# ============================================================
# 5. PREPARE & LAUNCH ACCOUNT 2 (DOT93845070) - 24 E/O BOTS IN 1 RUNNER CONTAINER
# ============================================================
ACC2_ID="DOT93845070"
ACC2_TOKEN="pat_e8b31d27beb9c0a040f1059ce12bac092383a3838554078c75378bf9831bf955"

echo "============================================================"
echo "🚀 Launching Account 2 ($ACC2_ID) - 24 Even/Odd Market-Switch Bots..."
echo "============================================================"

cat << 'EOF' > /root/run_acc2_fleet.sh
#!/bin/bash
ACC2_ID="DOT93845070"
ACC2_TOKEN="pat_e8b31d27beb9c0a040f1059ce12bac092383a3838554078c75378bf9831bf955"
MASTER_LOCK_ACC2="/root/shared_master_trade_lock_acc2"

spawn_team() {
  local PREFIX=$1
  local DIR_PREFIX=$2
  local BASE_OFFSET=$3
  for i in 1 2 3 4; do
    local BOT_NAME="acc2-${PREFIX}-$i"
    local BOT_DIR="/root/acc2_${DIR_PREFIX}_$i"
    local DELAY=$(( BASE_OFFSET + (i - 1) * 300 ))
    mkdir -p "$BOT_DIR"
    cp /root/eo_fleet_build/config.json "$BOT_DIR/config.json"
    cp /root/eo_fleet_build/even_odd_millipede.py "$BOT_DIR/even_odd_millipede.py"
    (
      cd "$BOT_DIR" || exit 1
      export BOT_NAME="$BOT_NAME"
      export DERIV_ACCOUNT_ID="$ACC2_ID"
      export DERIV_API_TOKEN="$ACC2_TOKEN"
      export SWITCH_MARKET_ON_LOSS="true"
      export INITIAL_DELAY_SECONDS="$DELAY"
      export LOCK_DIR="$MASTER_LOCK_ACC2"
      START_TS=$(date +%s)
      python3 -c "import json; json.dump({'name': '$BOT_NAME', 'pid': $BASHPID, 'started_at': $START_TS}, open('$BOT_DIR/bot_meta.json', 'w'))"
      while true; do
        python3 -u even_odd_millipede.py >> "$BOT_DIR/bot.log" 2>&1
        export INITIAL_DELAY_SECONDS="5"
        sleep 5
      done
    ) &
  done
}

spawn_team "even-odd-bot"          "even_odd_millipede_bot" 0
spawn_team "even-odd-fleet2-bot"   "even_odd_fleet2_bot"    45
spawn_team "over-under-fleet-bot"  "over_under_fleet_bot"   90
spawn_team "over-under-fleet2-bot" "over_under_fleet2_bot"  135
spawn_team "over-under-fleet3-bot" "over_under_fleet3_bot"  180
spawn_team "even-odd-fleet3-bot"   "even_odd_fleet3_bot"    225
wait
EOF
chmod +x /root/run_acc2_fleet.sh

docker run -d --restart always --name acc2-fleet-runner \
  --pid=host \
  -v /root:/root \
  --entrypoint /bin/bash \
  headless-even-odd-millipede /root/run_acc2_fleet.sh

echo "✅ Account 2: All 6 Even/Odd Market-Switch Teams launched [24 bots in 1 lightweight container]."

# ============================================================
# 6. PREPARE & LAUNCH ACCOUNT 3 (DOT91362122) - 24 C/P BOTS IN 1 RUNNER CONTAINER
# ============================================================
ACC3_ID="DOT91362122"
ACC3_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"

echo "============================================================"
echo "🚀 Launching Account 3 ($ACC3_ID) - 24 Call/Put Market-Switch Bots..."
echo "============================================================"

cat << 'EOF' > /root/run_acc3_fleet.sh
#!/bin/bash
ACC3_ID="DOT91362122"
ACC3_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a3838554078c75378bf9831bf955"
MASTER_LOCK_ACC3="/root/shared_master_trade_lock_acc3"

spawn_team() {
  local PREFIX=$1
  local DIR_PREFIX=$2
  local BASE_OFFSET=$3
  for i in 1 2 3 4; do
    local BOT_NAME="acc3-${PREFIX}-$i"
    local BOT_DIR="/root/acc3_${DIR_PREFIX}_$i"
    local DELAY=$(( BASE_OFFSET + (i - 1) * 300 ))
    mkdir -p "$BOT_DIR"
    cp /root/cp_fleet_build/config.json "$BOT_DIR/config.json"
    cp /root/cp_fleet_build/call_put_fleet.py "$BOT_DIR/call_put_fleet.py"
    (
      cd "$BOT_DIR" || exit 1
      export BOT_NAME="$BOT_NAME"
      export DERIV_ACCOUNT_ID="$ACC3_ID"
      export DERIV_API_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"
      export SWITCH_MARKET_ON_LOSS="true"
      export INITIAL_DELAY_SECONDS="$DELAY"
      export LOCK_DIR="$MASTER_LOCK_ACC3"
      START_TS=$(date +%s)
      python3 -c "import json; json.dump({'name': '$BOT_NAME', 'pid': $BASHPID, 'started_at': $START_TS}, open('$BOT_DIR/bot_meta.json', 'w'))"
      while true; do
        python3 -u call_put_fleet.py >> "$BOT_DIR/bot.log" 2>&1
        export INITIAL_DELAY_SECONDS="5"
        sleep 5
      done
    ) &
  done
}

spawn_team "even-odd-bot"          "even_odd_millipede_bot" 15
spawn_team "even-odd-fleet2-bot"   "even_odd_fleet2_bot"    60
spawn_team "over-under-fleet-bot"  "over_under_fleet_bot"   105
spawn_team "over-under-fleet2-bot" "over_under_fleet2_bot"  150
spawn_team "over-under-fleet3-bot" "over_under_fleet3_bot"  195
spawn_team "even-odd-fleet3-bot"   "even_odd_fleet3_bot"    240
wait
EOF
chmod +x /root/run_acc3_fleet.sh

docker run -d --restart always --name acc3-fleet-runner \
  --pid=host \
  -v /root:/root \
  --entrypoint /bin/bash \
  headless-call-put-fleet /root/run_acc3_fleet.sh

echo "✅ Account 3: All 6 Call/Put Market-Switch Teams launched [24 bots in 1 lightweight container]."

# 7. Update and restart the live pusher script (preserving existing tokens)
echo "🔄 Updating and restarting live monitor pusher..."
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

sleep 3
echo ""
echo "============================================================"
echo "🎉 ACCOUNT 2 & ACCOUNT 3 DEPLOYED SUCCESSFULLY!"
echo "   • Account 1 (DOT91203477): 24 E/O Bots (Lock Recovery)   - UNTOUCHED & RUNNING"
echo "   • Account 2 (DOT93845070): 24 E/O Bots (Switch Recovery) - LIVE NOW (acc2-fleet-runner)"
echo "   • Account 3 (DOT91362122): 24 C/P Bots (Switch Recovery) - LIVE NOW (acc3-fleet-runner)"
echo "   • Bybit Fleet:             6 Crypto Bots                 - UNTOUCHED & RUNNING"
echo "   • Dashboard Live at: https://fleet-bot-monitor.vercel.app"
echo "============================================================"
free -h
