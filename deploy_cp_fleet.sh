#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING 6-BOT CALL/PUT FLEET (30-MIN REST COOLDOWN)"
echo "   • Strategy: Trend Momentum Rise/Fall (CALL / PUT)"
echo "   • Rotation: 6 Bots Staggered Every 5 Minutes"
echo "   • Cooldown: 30-minute Win & Recovery Rest (1 Trade / 5 Min)"
echo "   • Recovery: 2.1 Martingale Step-Up ($0.35 Base)"
echo "   • Markets: 10 Even/Odd Markets (1HZ10V-100V, RDBULL, RDBEAR)
   • Lock: Isolated at /root/shared_trade_lock_cp"
echo "============================================================"

# 1. Clean previous Call/Put Fleet containers (DO NOT touch Even/Odd or Over/Under!)
echo "🧹 Checking & cleaning any previous Call/Put Fleet containers..."
for i in 1 2 3 4 5 6; do
  docker stop my-call-put-fleet-bot-$i 2>/dev/null || true
  docker rm my-call-put-fleet-bot-$i 2>/dev/null || true
  rm -f /root/call_put_fleet_bot_$i/state.json 2>/dev/null || true
done

# 2. Setup isolated shared trade lock for Call/Put fleet
SHARED_LOCK="/root/shared_trade_lock_cp"
mkdir -p "$SHARED_LOCK"
rm -rf "$SHARED_LOCK/trade_lock" "$SHARED_LOCK/lock_info.json"
echo "✅ Dedicated Call/Put trade lock initialized at $SHARED_LOCK"

# 3. Download source code for build
BUILD_DIR="/root/call_put_fleet_build"
mkdir -p "$BUILD_DIR"
echo "📥 Fetching Call/Put Fleet code from repository..."
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/cp_fleet/call_put_fleet.py > "$BUILD_DIR/call_put_fleet.py"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/cp_fleet/config.json > "$BUILD_DIR/config.json"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/cp_fleet/Dockerfile > "$BUILD_DIR/Dockerfile"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/cp_fleet/requirements.txt > "$BUILD_DIR/requirements.txt"

# 4. Build Docker image
echo "🔨 Building Docker image headless-call-put-fleet..."
cd "$BUILD_DIR"
docker build -t headless-call-put-fleet .

# 5. Launch 6 staggered Call/Put Fleet bots with fresh clean start
STAGGER_STEP=300
for i in 1 2 3 4 5 6; do
  BOT_NAME="my-call-put-fleet-bot-$i"
  BOT_DIR="/root/call_put_fleet_bot_$i"
  DELAY=$(( (i - 1) * STAGGER_STEP ))
  
  mkdir -p "$BOT_DIR"
  cp "$BUILD_DIR/config.json" "$BOT_DIR/config.json"
  cp "$BUILD_DIR/call_put_fleet.py" "$BOT_DIR/call_put_fleet.py"
  
  # Wipe state for a 100% fresh clean start
  rm -f "$BOT_DIR/state.json"
  
  echo "🚀 Launching $BOT_NAME (Delay: $((DELAY / 60))m)..."
  docker run -d --restart always \
    --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" \
    -v "$SHARED_LOCK:/app/lock" \
    headless-call-put-fleet
done

# 6. Update and restart the live pusher script
echo "🔄 Updating live monitor pusher with Call/Put detection..."
pkill -f fleet_monitor_pusher.py 2>/dev/null || true
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/fleet_monitor_pusher.py > /root/fleet_monitor_pusher.py
if [ -f /root/run_pusher.sh ]; then
  /root/run_pusher.sh
else
  nohup python3 -u /root/fleet_monitor_pusher.py > /root/pusher.log 2>&1 &
fi

echo ""
echo "============================================================"
echo "🎉 DEPLOYMENT SUCCESSFUL!"
echo "   • 6 Call/Put Fleet bots running fresh with 30-min cooldown!"
echo "   • Even/Odd and Over/Under fleets remain 100% untouched!"
echo "   • Live status is pushing to your Webapp dashboard!"
echo "============================================================"
docker ps --filter "name=my-call-put"
