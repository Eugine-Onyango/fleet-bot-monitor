#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING ALL 6 FLEET BOTS (ALL 6 FLEETS EVEN/ODD • 24 BOTS TOTAL)"
echo "   • Fleets (6 Total, 24 Bots):"
echo "       1. Even/Odd Team 1               (4 Bots, Even/Odd, 20m Rest)"
echo "       2. Even/Odd Team 2               (4 Bots, Even/Odd, 20m Rest)"
echo "       3. Over/Under (Converted) Team 1 (4 Bots, Even/Odd, 20m Rest)"
echo "       4. Over/Under (Converted) Team 2 (4 Bots, Even/Odd, 20m Rest)"
echo "       5. Call/Put (Converted) Team 1   (4 Bots, Even/Odd, 20m Rest)"
echo "       6. Call/Put (Converted) Team 2   (4 Bots, Even/Odd, 20m Rest)"
echo "   • Strategy: 100% Even / Odd Digits Strategy across all 24 bots"
echo "   • Markets: Single Fast 10s Index (1HZ10V) • All other markets disabled"
echo "   • Timing: 20-Minute Cooldown with 4 Bots Staggered Every 5 Minutes"
echo "   • Coordination: Unified Master Trade Lock + 45s Offset"
echo "   • Clean Start: All Deriv states & profits reset to \$0.00 (Bybit untouched)"
echo "============================================================"

# 1. Clean previous containers across all Deriv fleets (DO NOT touch Bybit Fleet!)
echo "🧹 Stopping and forcefully removing all existing Deriv bot containers..."
docker ps -aq --filter "name=my-even-odd" --filter "name=my-over-under" --filter "name=my-call-put" | xargs -r docker rm -f 2>/dev/null || true

for i in $(seq 1 10); do
  docker rm -f my-even-odd-bot-$i 2>/dev/null || true
  docker rm -f my-even-odd-fleet2-bot-$i 2>/dev/null || true
  docker rm -f my-even-odd-fleet3-bot-$i 2>/dev/null || true
  docker rm -f my-over-under-fleet-bot-$i 2>/dev/null || true
  docker rm -f my-over-under-fleet2-bot-$i 2>/dev/null || true
  docker rm -f my-over-under-fleet3-bot-$i 2>/dev/null || true
  docker rm -f my-call-put-fleet-bot-$i 2>/dev/null || true
  docker rm -f my-call-put-fleet2-bot-$i 2>/dev/null || true
done

# 2. Wipe Deriv state.json files for 100% fresh clean start (Preserving Bybit state & peaks!)
echo "✨ Wiping old Deriv state files for a 100% fresh clean start..."
rm -f /root/even_odd_millipede_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet2_bot_*/state.json 2>/dev/null || true

# Reset Deriv peak profits while keeping Bybit peaks 100% intact
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
  with open('/root/fleet_peak_profits.json', 'w') as f:
    json.dump(d, f, indent=2)
except Exception:
  pass
" 2>/dev/null || true
else
  echo '{"overall": 0.0, "reset_at": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "systems": {"eo": 0.0, "ou": 0.0, "cp": 0.0, "bybit": 0.0}, "fleets": {}, "bots": {}}' > /root/fleet_peak_profits.json
fi

# 3. Setup unified master trade lock directory
MASTER_LOCK="/root/shared_master_trade_lock"
mkdir -p "$MASTER_LOCK"
rm -rf "$MASTER_LOCK/trade_lock" "$MASTER_LOCK/lock_info.json"
echo "🔒 Unified Master Trade Lock initialized at $MASTER_LOCK"

# 4. Fetch and build Docker image
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"

# Even/Odd Image (Used by ALL 6 Fleets)
echo "🔨 Building image: headless-even-odd-millipede..."
EO_BUILD="/root/eo_fleet_build"
mkdir -p "$EO_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > "$EO_BUILD/even_odd_millipede.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > "$EO_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/Dockerfile" > "$EO_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/requirements.txt" > "$EO_BUILD/requirements.txt"
cd "$EO_BUILD"
docker build -t headless-even-odd-millipede .

# 5. Synchronization (Immediate Fresh Start with 45s Offset Stagger)
WAIT_SECS=0

echo "============================================================"
echo "⏰ Starting all 24 Deriv bots immediately with 45s staggered offsets across fleets"
echo "⏳ Fresh start initiated at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"

echo "🚀 Launching all 6 fleets (4 Bots Each, 20m Rest, 1 Trade / 5m)..."

# Fleet 1: Even/Odd Team 1 (4 Bots) - Base Offset: 0s
for i in 1 2 3 4; do
  BOT_NAME="my-even-odd-bot-$i"
  BOT_DIR="/root/even_odd_millipede_bot_$i"
  DELAY=$(( WAIT_SECS + 0 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 1 (Even/Odd Team 1) launched [4 bots]."

# Fleet 2: Even/Odd Team 2 (4 Bots) - Base Offset: 45s
for i in 1 2 3 4; do
  BOT_NAME="my-even-odd-fleet2-bot-$i"
  BOT_DIR="/root/even_odd_fleet2_bot_$i"
  DELAY=$(( WAIT_SECS + 45 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 2 (Even/Odd Team 2) launched [4 bots]."

# Fleet 3: Over/Under Team 1 (Converted to Even/Odd, 4 Bots) - Base Offset: 90s
for i in 1 2 3 4; do
  BOT_NAME="my-over-under-fleet-bot-$i"
  BOT_DIR="/root/over_under_fleet_bot_$i"
  DELAY=$(( WAIT_SECS + 90 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 3 (Over/Under Team 1 Converted to Even/Odd) launched [4 bots]."

# Fleet 4: Over/Under Team 2 (Converted to Even/Odd, 4 Bots) - Base Offset: 135s
for i in 1 2 3 4; do
  BOT_NAME="my-over-under-fleet2-bot-$i"
  BOT_DIR="/root/over_under_fleet2_bot_$i"
  DELAY=$(( WAIT_SECS + 135 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 4 (Over/Under Team 2 Converted to Even/Odd) launched [4 bots]."

# Fleet 5: Call/Put Converted Team 1 (4 Bots, Even/Odd) - Base Offset: 180s
for i in 1 2 3 4; do
  BOT_NAME="my-over-under-fleet3-bot-$i"
  BOT_DIR="/root/over_under_fleet3_bot_$i"
  DELAY=$(( WAIT_SECS + 180 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 5 (Call/Put Converted Team 1 Even/Odd) launched [4 bots]."

# Fleet 6: Call/Put Converted Team 2 (4 Bots, Even/Odd) - Base Offset: 225s
for i in 1 2 3 4; do
  BOT_NAME="my-even-odd-fleet3-bot-$i"
  BOT_DIR="/root/even_odd_fleet3_bot_$i"
  DELAY=$(( WAIT_SECS + 225 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$EO_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$EO_BUILD/even_odd_millipede.py" "$BOT_DIR/even_odd_millipede.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-even-odd-millipede
done
echo "✅ Fleet 6 (Call/Put Converted Team 2 Even/Odd) launched [4 bots]."

# 6. Update and restart the live pusher script (preserving existing tokens)
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
echo "🎉 ALL 6 DERIV FLEETS DEPLOYED WITH FRESH CLEAN START!"
echo "   • Strategy: 100% Even / Odd Digits across all 24 bots"
echo "   • Fleets (6 Total, 24 Bots):"
echo "       - Tab 1: Even / Odd               (Team 1 & Team 2 - 8 bots)"
echo "       - Tab 2: Over / Under (Converted) (Team 1 & Team 2 - 8 bots)"
echo "       - Tab 3: Call / Put (Converted)   (Team 3 & Team 4 - 8 bots)"
echo "   • Market: Single Fast Volatility 10 (1s) Index [1HZ10V]"
echo "   • Cooldown: 20-Minute Rest (1 Trade Every 5 Minutes per Team)"
echo "   • Master Trade Lock: /root/shared_master_trade_lock (0 collisions)"
echo "   • Fleets Offset: 45s stagger gap between fleet cycles"
echo "   • Bybit Fleet: 100% Untouched and active in the background!"
echo "   • Dashboard Live at: https://fleet-bot-monitor.vercel.app"
echo "============================================================"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
