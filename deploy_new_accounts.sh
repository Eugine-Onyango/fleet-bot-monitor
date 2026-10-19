#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING ACCOUNT 2 & ACCOUNT 3 FLEETS (48 NEW BOTS TOTAL)"
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

# 1. Clean ONLY Account 2 & Account 3 containers (DO NOT touch Account 1 or Bybit!)
echo "🧹 Cleaning any previous Account 2 (acc2-*) and Account 3 (acc3-*) containers..."
docker ps -aq --filter "name=acc2-" --filter "name=acc3-" | xargs -r docker rm -f 2>/dev/null || true

# 2. Wipe ONLY Account 2 & Account 3 state files
echo "✨ Initializing clean state directories for Account 2 & Account 3..."
rm -rf /root/acc2_*_bot_*/state.json 2>/dev/null || true
rm -rf /root/acc3_*_bot_*/state.json 2>/dev/null || true

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

# 4. Fetch and build Docker images
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"

echo "🔨 Building image: headless-even-odd-millipede..."
EO_BUILD="/root/eo_fleet_build"
mkdir -p "$EO_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > "$EO_BUILD/even_odd_millipede.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > "$EO_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/Dockerfile" > "$EO_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/requirements.txt" > "$EO_BUILD/requirements.txt"
cd "$EO_BUILD"
docker build -t headless-even-odd-millipede .

echo "🔨 Building image: headless-call-put-fleet..."
CP_BUILD="/root/cp_fleet_build"
mkdir -p "$CP_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/call_put_fleet.py" > "$CP_BUILD/call_put_fleet.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/config.json" > "$CP_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/Dockerfile" > "$CP_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/requirements.txt" > "$CP_BUILD/requirements.txt"
cd "$CP_BUILD"
docker build -t headless-call-put-fleet .

# ============================================================
# 5. LAUNCH ACCOUNT 2 (DOT93845070) - 6 EVEN/ODD TEAMS (MARKET-SWITCH RECOVERY)
# ============================================================
ACC2_ID="DOT93845070"
ACC2_TOKEN="pat_e8b31d27beb9c0a040f1059ce12bac092383a3838554078c75378bf9831bf955"

echo "============================================================"
echo "🚀 Launching Account 2 ($ACC2_ID) - 24 Even/Odd Market-Switch Bots..."
echo "============================================================"

launch_acc2_team() {
  local PREFIX=$1
  local DIR_PREFIX=$2
  local BASE_OFFSET=$3
  for i in 1 2 3 4; do
    BOT_NAME="acc2-${PREFIX}-$i"
    BOT_DIR="/root/acc2_${DIR_PREFIX}_$i"
    DELAY=$(( BASE_OFFSET + (i - 1) * 300 ))
    mkdir -p "$BOT_DIR"
    cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
    cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
    rm -f "$BOT_DIR/state.json"
    docker run -d --restart always --name "$BOT_NAME" \
      -e BOT_NAME="$BOT_NAME" \
      -e DERIV_ACCOUNT_ID="$ACC2_ID" \
      -e DERIV_API_TOKEN="$ACC2_TOKEN" \
      -e SWITCH_MARKET_ON_LOSS="true" \
      -e INITIAL_DELAY_SECONDS="$DELAY" \
      -v "$BOT_DIR:/app" -v "$MASTER_LOCK_ACC2:/app/lock" \
      headless-even-odd-millipede
  done
}

launch_acc2_team "even-odd-bot"         "even_odd_millipede_bot" 0
launch_acc2_team "even-odd-fleet2-bot"  "even_odd_fleet2_bot"    45
launch_acc2_team "over-under-fleet-bot" "over_under_fleet_bot"   90
launch_acc2_team "over-under-fleet2-bot" "over_under_fleet2_bot" 135
launch_acc2_team "over-under-fleet3-bot" "over_under_fleet3_bot" 180
launch_acc2_team "even-odd-fleet3-bot"  "even_odd_fleet3_bot"    225
echo "✅ Account 2: All 6 Even/Odd Market-Switch Teams launched [24 bots]."

# ============================================================
# 6. LAUNCH ACCOUNT 3 (DOT91362122) - 6 CALL/PUT TEAMS (MARKET-SWITCH RECOVERY)
# ============================================================
ACC3_ID="DOT91362122"
ACC3_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"

echo "============================================================"
echo "🚀 Launching Account 3 ($ACC3_ID) - 24 Call/Put Market-Switch Bots..."
echo "============================================================"

launch_acc3_team() {
  local PREFIX=$1
  local DIR_PREFIX=$2
  local BASE_OFFSET=$3
  for i in 1 2 3 4; do
    BOT_NAME="acc3-${PREFIX}-$i"
    BOT_DIR="/root/acc3_${DIR_PREFIX}_$i"
    DELAY=$(( BASE_OFFSET + (i - 1) * 300 ))
    mkdir -p "$BOT_DIR"
    cp "$CP_BUILD/config.json" "$BOT_DIR/config.json"
    cp "$CP_BUILD/call_put_fleet.py" "$BOT_DIR/call_put_fleet.py"
    rm -f "$BOT_DIR/state.json"
    docker run -d --restart always --name "$BOT_NAME" \
      -e BOT_NAME="$BOT_NAME" \
      -e DERIV_ACCOUNT_ID="$ACC3_ID" \
      -e DERIV_API_TOKEN="$ACC3_TOKEN" \
      -e SWITCH_MARKET_ON_LOSS="true" \
      -e INITIAL_DELAY_SECONDS="$DELAY" \
      -v "$BOT_DIR:/app" -v "$MASTER_LOCK_ACC3:/app/lock" \
      headless-call-put-fleet
  done
}

launch_acc3_team "even-odd-bot"         "even_odd_millipede_bot" 15
launch_acc3_team "even-odd-fleet2-bot"  "even_odd_fleet2_bot"    60
launch_acc3_team "over-under-fleet-bot" "over_under_fleet_bot"   105
launch_acc3_team "over-under-fleet2-bot" "over_under_fleet2_bot" 150
launch_acc3_team "over-under-fleet3-bot" "over_under_fleet3_bot" 195
launch_acc3_team "even-odd-fleet3-bot"  "even_odd_fleet3_bot"    240
echo "✅ Account 3: All 6 Call/Put Market-Switch Teams launched [24 bots]."

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

echo ""
echo "============================================================"
echo "🎉 ACCOUNT 2 & ACCOUNT 3 DEPLOYED SUCCESSFULLY!"
echo "   • Account 1 (DOT91203477): 24 E/O Bots (Lock Recovery)   - UNTOUCHED & RUNNING"
echo "   • Account 2 (DOT93845070): 24 E/O Bots (Switch Recovery) - LIVE NOW"
echo "   • Account 3 (DOT91362122): 24 C/P Bots (Switch Recovery) - LIVE NOW"
echo "   • Bybit Fleet:             6 Crypto Bots                 - UNTOUCHED & RUNNING"
echo "   • Dashboard Live at: https://fleet-bot-monitor.vercel.app"
echo "============================================================"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | head -n 40
