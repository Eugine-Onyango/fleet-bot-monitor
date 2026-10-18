#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING 4-BOT BYBIT LONG/SHORT FLEET (20-MIN COOLDOWN)"
echo "   • Mode: Bybit Demo Trading (https://api-demo.bybit.com)"
echo "   • Strategy: Trend Momentum LONG / SHORT (2-Step Switch)"
echo "   • Rotation: 4 Bots Staggered Every 5 Minutes (0m, 5m, 10m, 15m)"
echo "   • Cooldown: 20-minute Win & Recovery Rest (1 Trade / 5 Min)"
echo "   • Daily Target: \$50.00 / day (Sleeps until midnight once hit)"
echo "   • Lock: Isolated at /root/shared_trade_lock_bybit"
echo "============================================================"

# 1. Clean any previous Bybit Fleet containers (DO NOT touch Deriv containers!)
echo "🧹 Checking & cleaning any previous Bybit Fleet containers..."
for i in 1 2 3 4 5 6; do
  docker stop my-bybit-fleet-bot-$i 2>/dev/null || true
  docker rm my-bybit-fleet-bot-$i 2>/dev/null || true
  rm -f /root/bybit_fleet_bot_$i/state.json 2>/dev/null || true
done

# 2. Setup isolated shared trade lock for Bybit fleet
SHARED_LOCK="/root/shared_trade_lock_bybit"
mkdir -p "$SHARED_LOCK"
rm -rf "$SHARED_LOCK/bybit_trade_lock" "$SHARED_LOCK/bybit_lock_info.json"
echo "✅ Dedicated Bybit trade lock initialized at $SHARED_LOCK"

# 3. Download source code for build
BUILD_DIR="/root/bybit_fleet_build"
mkdir -p "$BUILD_DIR"
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/bybit_fleet"
echo "📥 Fetching Bybit Fleet code from repository..."
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/bybit_fleet.py" > "$BUILD_DIR/bybit_fleet.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/config.json" > "$BUILD_DIR/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/Dockerfile" > "$BUILD_DIR/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/requirements.txt" > "$BUILD_DIR/requirements.txt"

# 4. Build Docker image
echo "🔨 Building Docker image headless-bybit-fleet..."
cd "$BUILD_DIR"
docker build -t headless-bybit-fleet .

# 5. Launch 4 staggered Bybit Fleet bots (0m, 5m, 10m, 15m)
STAGGER_STEP=300
for i in 1 2 3 4; do
  BOT_NAME="my-bybit-fleet-bot-$i"
  BOT_DIR="/root/bybit_fleet_bot_$i"
  DELAY=$(( (i - 1) * STAGGER_STEP ))

  mkdir -p "$BOT_DIR"
  cp "$BUILD_DIR/config.json" "$BOT_DIR/config.json"
  cp "$BUILD_DIR/bybit_fleet.py" "$BOT_DIR/bybit_fleet.py"
  rm -f "$BOT_DIR/state.json"

  echo "🚀 Launching $BOT_NAME (Delay: $((DELAY / 60))m)..."
  docker run -d --restart always \
    --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -e BYBIT_API_KEY="$BYBIT_API_KEY" \
    -e BYBIT_API_SECRET="$BYBIT_API_SECRET" \
    -v "$BOT_DIR:/app" \
    -v "$SHARED_LOCK:/app/lock" \
    headless-bybit-fleet
done

echo ""
echo "============================================================"
echo "🎉 BYBIT FLEET DEPLOYMENT SUCCESSFUL!"
echo "   • 4 Bybit Fleet bots running with 20-min cooldown (1 trade / 5m)!"
echo "   • Daily Take Profit target: \$50.00"
echo "   • All Deriv Binary fleets remain 100% untouched!"
echo "============================================================"
docker ps --filter "name=my-bybit-fleet-bot"
