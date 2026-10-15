#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING 50/50 OVER/UNDER FLEET BOT (2.1 MARTINGALE)"
echo "   • Strategy: 50% Over 4 / Under 5 Digit Scanner"
echo "   • Recovery: 2.1 Martingale (0.35 Base Stake)"
echo "   • Rest: 20-minute Win & Recovery Cooldowns"
echo "   • Clones: 4 Bots Staggered Every 5 Minutes"
echo "============================================================"

# 1. Clean previous Over/Under Fleet containers and old states
echo "🧹 Checking & cleaning previous Over/Under Fleet containers..."
for i in 1 2 3 4; do
  docker stop my-over-under-fleet-bot-$i 2>/dev/null || true
  docker rm my-over-under-fleet-bot-$i 2>/dev/null || true
  rm -f /root/over_under_fleet_bot_$i/state.json 2>/dev/null || true
done

# 2. Setup shared trade lock for Over/Under fleet
SHARED_LOCK="/root/shared_trade_lock_ou"
mkdir -p "$SHARED_LOCK"
rm -rf "$SHARED_LOCK/trade_lock" "$SHARED_LOCK/lock_info.json"
echo "✅ Dedicated trade lock initialized at $SHARED_LOCK"

# 3. Download source code for build
BUILD_DIR="/root/over_under_fleet_build"
mkdir -p "$BUILD_DIR"
echo "📥 Fetching Over/Under Fleet code from repository..."
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/ou_fleet/over_under_fleet.py > "$BUILD_DIR/over_under_fleet.py"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/ou_fleet/config.json > "$BUILD_DIR/config.json"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/ou_fleet/Dockerfile > "$BUILD_DIR/Dockerfile"
curl -s -H "Cache-Control: no-cache" https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/ou_fleet/requirements.txt > "$BUILD_DIR/requirements.txt"

# 4. Build Docker image
echo "🔨 Building Docker image headless-over-under-fleet..."
cd "$BUILD_DIR"
docker build -t headless-over-under-fleet .

# 5. Launch 4 staggered Over/Under Fleet bots with fresh clean start
STAGGER_STEP=300
for i in 1 2 3 4; do
  BOT_NAME="my-over-under-fleet-bot-$i"
  BOT_DIR="/root/over_under_fleet_bot_$i"
  DELAY=$(( (i - 1) * STAGGER_STEP ))
  
  mkdir -p "$BOT_DIR"
  cp "$BUILD_DIR/config.json" "$BOT_DIR/config.json"
  cp "$BUILD_DIR/over_under_fleet.py" "$BOT_DIR/over_under_fleet.py"
  
  # Wipe state for a 100% fresh clean start
  rm -f "$BOT_DIR/state.json"
  
  echo "🚀 Launching $BOT_NAME (Delay: $((DELAY / 60))m)..."
  docker run -d --restart always \
    --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" \
    -v "$SHARED_LOCK:/app/lock" \
    headless-over-under-fleet
done

# 6. Update and restart the live pusher script
echo "🔄 Updating live monitor pusher..."
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
echo "   • 4 Over/Under Fleet bots running fresh with 2.1 Martingale!"
echo "   • Live status is pushing to your Webapp dashboard!"
echo "============================================================"
docker ps --filter "name=my-over-under"
