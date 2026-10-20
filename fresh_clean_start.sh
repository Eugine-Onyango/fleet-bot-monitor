#!/bin/bash
set -e

echo "============================================================"
echo "✨ FRESH CLEAN START FOR ALL DERIV FLEETS (72 BOTS TOTAL)"
echo "   • Account 1 (DOT91203477): 24 E/O Bots (Lock Recovery)   -> RESET & RESTART"
echo "   • Account 2 (DOT93845070): 24 E/O Bots (Switch Recovery) -> RESET & RESTART"
echo "   • Account 3 (DOT91362122): 24 C/P Bots (Switch Recovery) -> RESET & RESTART"
echo "   • Bybit Fleet (Crypto):    6 Bots                        -> 100% UNTOUCHED"
echo "============================================================"

# ------------------------------------------------------------
# 1. STOP & WIPE ACCOUNT 1 (DOT91203477 - 24 BOTS)
# ------------------------------------------------------------
echo "🛑 Stopping Account 1 bot containers..."
docker ps -q --filter "name=my-even-odd" --filter "name=my-over-under" --filter "name=my-call-put" | xargs -r docker stop >/dev/null 2>&1 || true

echo "🧹 Wiping Account 1 state files & locks..."
rm -f /root/even_odd_millipede_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet2_bot_*/state.json 2>/dev/null || true
rm -rf /root/shared_master_trade_lock/trade_lock /root/shared_master_trade_lock/lock_info.json

# ------------------------------------------------------------
# 2. STOP & WIPE ACCOUNT 2 (DOT93845070 - 24 BOTS)
# ------------------------------------------------------------
echo "🛑 Stopping Account 2 runner..."
docker rm -f acc2-fleet-runner >/dev/null 2>&1 || true
pkill -f "run_acc2_fleet" 2>/dev/null || true
pkill -f "DOT93845070" 2>/dev/null || true

echo "🧹 Wiping Account 2 state files & locks..."
rm -rf /root/acc2_*_bot_*/state.json /root/acc2_*_bot_*/bot.log /root/acc2_*_bot_*/bot_meta.json 2>/dev/null || true
rm -rf /root/shared_master_trade_lock_acc2/trade_lock /root/shared_master_trade_lock_acc2/lock_info.json

# ------------------------------------------------------------
# 3. STOP & WIPE ACCOUNT 3 (DOT91362122 - 24 BOTS)
# ------------------------------------------------------------
echo "🛑 Stopping Account 3 runner..."
docker rm -f acc3-fleet-runner >/dev/null 2>&1 || true
pkill -f "run_acc3_fleet" 2>/dev/null || true
pkill -f "DOT91362122" 2>/dev/null || true

echo "🧹 Wiping Account 3 state files & locks..."
rm -rf /root/acc3_*_bot_*/state.json /root/acc3_*_bot_*/bot.log /root/acc3_*_bot_*/bot_meta.json 2>/dev/null || true
rm -rf /root/shared_master_trade_lock_acc3/trade_lock /root/shared_master_trade_lock_acc3/lock_info.json

# ------------------------------------------------------------
# 4. RESET DERIV PEAK PROFITS (KEEP BYBIT PEAK PROFIT 100% INTACT)
# ------------------------------------------------------------
echo "🎯 Resetting Deriv historical peaks to \$0.00 (Bybit preserved)..."
if [ -f /root/fleet_peak_profits.json ]; then
  python3 -c "
import json
try:
  with open('/root/fleet_peak_profits.json', 'r') as f:
    d = json.load(f)
  d['reset_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
  if 'systems' in d:
    d['systems']['eo'] = 0.0
    d['systems']['ou'] = 0.0
    d['systems']['cp'] = 0.0
  acc_sys = d.setdefault('account_systems', {})
  for k in ['acc2_eo', 'acc2_ou', 'acc2_cp', 'acc3_eo', 'acc3_ou', 'acc3_cp']:
    acc_sys[k] = 0.0
  with open('/root/fleet_peak_profits.json', 'w') as f:
    json.dump(d, f, indent=2)
except Exception as e:
  print(f'Warning resetting peak profits: {e}')
" 2>/dev/null || true
fi

# ------------------------------------------------------------
# 5. RESTART ACCOUNT 1 (24 BOTS WITH CLEAN STAGGER SCHEDULE)
# ------------------------------------------------------------
echo "🚀 Restarting Account 1 (24 Even/Odd Bots - Lock Recovery)..."
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"
mkdir -p /root/eo_fleet_build /root/cp_fleet_build
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > /root/eo_fleet_build/even_odd_millipede.py
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > /root/eo_fleet_build/config.json
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/call_put_fleet.py" > /root/cp_fleet_build/call_put_fleet.py
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/cp_fleet/config.json" > /root/cp_fleet_build/config.json

# Copy clean code to all Account 1 bot directories
for d in /root/even_odd_millipede_bot_* /root/even_odd_fleet2_bot_* /root/even_odd_fleet3_bot_* \
         /root/over_under_fleet_bot_* /root/over_under_fleet2_bot_* /root/over_under_fleet3_bot_*; do
  if [ -d "$d" ]; then
    cp /root/eo_fleet_build/config.json "$d/config.json" 2>/dev/null || true
    cp /root/eo_fleet_build/even_odd_millipede.py "$d/even_odd_millipede.py" 2>/dev/null || true
  fi
done

docker ps -aq --filter "name=my-even-odd" --filter "name=my-over-under" --filter "name=my-call-put" | xargs -r docker start >/dev/null 2>&1 || true
echo "✅ Account 1: All 24 Bots restarted with clean slate."

# ------------------------------------------------------------
# 6. RESTART ACCOUNT 2 (24 BOTS - MARKET-SWITCH RECOVERY)
# ------------------------------------------------------------
echo "🚀 Restarting Account 2 (24 Even/Odd Bots - Market-Switch Recovery)..."
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
  headless-even-odd-millipede /root/run_acc2_fleet.sh >/dev/null
echo "✅ Account 2: 24 Bots launched in clean runner."

# ------------------------------------------------------------
# 7. RESTART ACCOUNT 3 (24 BOTS - MARKET-SWITCH RECOVERY)
# ------------------------------------------------------------
echo "🚀 Restarting Account 3 (24 Call/Put Bots - Market-Switch Recovery)..."
cat << 'EOF' > /root/run_acc3_fleet.sh
#!/bin/bash
ACC3_ID="DOT91362122"
ACC3_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"
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
      export DERIV_API_TOKEN="$ACC3_TOKEN"
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
  headless-call-put-fleet /root/run_acc3_fleet.sh >/dev/null
echo "✅ Account 3: 24 Bots launched in clean runner."

# ------------------------------------------------------------
# 8. UPDATE AND RESTART MONITOR PUSHER
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

sleep 3
echo ""
echo "============================================================"
echo "🎉 ALL DERIV FLEETS HAVE BEEN GIVEN A FRESH CLEAN START!"
echo "   • Account 1 (DOT91203477): 24 E/O Bots (Lock Recovery)   - RESET & RUNNING"
echo "   • Account 2 (DOT93845070): 24 E/O Bots (Switch Recovery) - RESET & RUNNING"
echo "   • Account 3 (DOT91362122): 24 C/P Bots (Switch Recovery) - RESET & RUNNING"
echo "   • Bybit Fleet:             6 Crypto Bots                 - 100% UNTOUCHED"
echo "   • All Deriv P/L reset to \$0.00 and win/loss records reset to 0-0."
echo "   • Dashboard Live at: https://fleet-bot-monitor.vercel.app"
echo "============================================================"
