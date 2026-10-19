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
rm -rf "$SHARED_LOCK/bybit_trade_lock" "$SHARED_LOCK/bybit_lock_info.json" "$SHARED_LOCK/daily_fleet_profit.json"
python3 -c '
import json, os
p = "/root/fleet_peak_profits.json"
if os.path.exists(p):
    try:
        with open(p, "r") as f: d = json.load(f)
        if "systems" in d: d["systems"]["bybit"] = 0.0
        if "fleets" in d: d["fleets"].pop("Fleet 1 (Bybit)", None)
        if "bots" in d:
            for k in [k for k in d["bots"] if "bybit" in k]:
                d["bots"].pop(k, None)
        with open(p, "w") as f: json.dump(d, f, indent=2)
    except Exception: pass
' 2>/dev/null || true
echo "✅ Dedicated Bybit trade lock & fresh stats initialized at $SHARED_LOCK"

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

# 6. Update live monitor pusher so Bybit Fleet tab shows on the Webapp (preserving existing token!)
echo "🔄 Updating live monitor pusher with Bybit Fleet detection..."
EXISTING_TOKEN=$(grep -oP 'GITHUB_TOKEN = os\.getenv\("GITHUB_TOKEN", "\K[^"]+' /root/fleet_monitor_pusher.py 2>/dev/null || true)
EXISTING_GIST=$(grep -oP 'GIST_ID = os\.getenv\("GIST_ID", "\K[^"]+' /root/fleet_monitor_pusher.py 2>/dev/null || true)
pkill -f fleet_monitor_pusher.py 2>/dev/null || true
curl -s -H "Cache-Control: no-cache" "https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main/fleet_monitor_pusher.py" > /root/fleet_monitor_pusher.py
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
echo "🎉 BYBIT FLEET DEPLOYMENT SUCCESSFUL!"
echo "   • 4 Bybit Fleet bots running with 20-min cooldown (1 trade / 5m)!"
echo "   • Daily Take Profit target: \$50.00"
echo "   • All Deriv Binary fleets remain 100% untouched!"
echo "   • Live status pushing to the new 🚀 Bybit Fleet tab on your Webapp!"
echo "============================================================"
docker ps --filter "name=my-bybit-fleet-bot"
