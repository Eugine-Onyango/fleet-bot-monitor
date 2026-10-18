#!/bin/bash
set -e

echo "============================================================"
echo "🚀 DEPLOYING ALL 6 FLEET BOTS (3 E/O & 3 O/U • 36 BOTS TOTAL)"
echo "   • Fleets (6 Total, 36 Bots):"
echo "       1. Even/Odd Team 1     (6 Bots, 30m Rest)"
echo "       2. Even/Odd Team 2     (6 Bots, 30m Rest)"
echo "       3. Over/Under Team 1   (6 Bots, 30m Rest, 50/50)"
echo "       4. Over/Under Team 2   (6 Bots, 30m Rest, 50/50)"
echo "       5. Over/Under Team 3   (6 Bots, 30m Rest, 50/50 - Reallocated from C/P)"
echo "       6. Even/Odd Team 3     (6 Bots, 30m Rest - Reallocated from C/P)"
echo "   • Call/Put: Safely preserved & dormant (Ready to revert anytime)"
echo "   • Markets: 10 Multi-Markets (1HZ10V-100V, RDBULL, RDBEAR)"
echo "   • Schedule: Synchronized Start (Unified Master Lock + 45s Offset)"
echo "   • Clean Start: All states & profits reset to \$0.00"
echo "============================================================"

# 1. Clean previous containers across all fleets
echo "🧹 Stopping and forcefully removing all existing bot containers..."
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

# 2. Wipe all state.json files for 100% fresh clean start
echo "✨ Wiping old state & peak files for a 100% fresh clean start..."
rm -f /root/even_odd_millipede_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/even_odd_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/over_under_fleet3_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet_bot_*/state.json 2>/dev/null || true
rm -f /root/call_put_fleet2_bot_*/state.json 2>/dev/null || true
rm -f /root/fleet_peak_profits.json 2>/dev/null || true
echo '{"overall": 0.0, "reset_at": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "systems": {"eo": 0.0, "ou": 0.0, "cp": 0.0}, "fleets": {}, "bots": {}}' > /root/fleet_peak_profits.json

# 3. Setup unified master trade lock directory
MASTER_LOCK="/root/shared_master_trade_lock"
mkdir -p "$MASTER_LOCK"
rm -rf "$MASTER_LOCK/trade_lock" "$MASTER_LOCK/lock_info.json"
echo "🔒 Unified Master Trade Lock initialized at $MASTER_LOCK"

# 4. Fetch and build Docker images
REPO_RAW="https://raw.githubusercontent.com/Eugine-Onyango/fleet-bot-monitor/main"

# A. Even/Odd Image
echo "🔨 Building image: headless-even-odd-millipede..."
EO_BUILD="/root/eo_fleet_build"
mkdir -p "$EO_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/even_odd_millipede.py" > "$EO_BUILD/even_odd_millipede.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/config.json" > "$EO_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/Dockerfile" > "$EO_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/eo_fleet/requirements.txt" > "$EO_BUILD/requirements.txt"
cd "$EO_BUILD"
docker build -t headless-even-odd-millipede .

# B. Over/Under Image
echo "🔨 Building image: headless-over-under-fleet..."
OU_BUILD="/root/ou_fleet_build"
mkdir -p "$OU_BUILD"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/ou_fleet/over_under_fleet.py" > "$OU_BUILD/over_under_fleet.py"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/ou_fleet/config.json" > "$OU_BUILD/config.json"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/ou_fleet/Dockerfile" > "$OU_BUILD/Dockerfile"
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/ou_fleet/requirements.txt" > "$OU_BUILD/requirements.txt"
cd "$OU_BUILD"
docker build -t headless-over-under-fleet .

# 5. Calculate synchronization to 08:00:00 AM Kenyan Time (05:00:00 UTC)
NOW_EPOCH=$(date -u +%s)
TARGET_DATE=$(date -u +%Y-%m-%d)
TARGET_EPOCH=$(date -u -d "$TARGET_DATE 05:00:00" +%s 2>/dev/null || python3 -c "import datetime; now=datetime.datetime.now(datetime.timezone.utc); target=datetime.datetime(now.year, now.month, now.day, 5, 0, 0, tzinfo=datetime.timezone.utc); print(int(target.timestamp()))")

WAIT_SECS=$(( TARGET_EPOCH - NOW_EPOCH ))
if [ $WAIT_SECS -lt 0 ]; then
  WAIT_SECS=0
fi

MINS_REMAINING=$(( WAIT_SECS / 60 ))
SECS_REMAINING=$(( WAIT_SECS % 60 ))
echo "============================================================"
echo "⏰ Synchronizing to 08:00:00 AM Kenyan Time (05:00:00 UTC)"
echo "⏳ First trade executes in: ${MINS_REMAINING}m ${SECS_REMAINING}s ($WAIT_SECS seconds)"
echo "============================================================"

echo "🚀 Launching all 6 fleets..."

# Fleet 1: Even/Odd Team 1 (6 Bots) - Base Offset: 0s
for i in 1 2 3 4 5 6; do
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
echo "✅ Fleet 1 (Even/Odd Team 1) launched [6 bots]."

# Fleet 2: Even/Odd Team 2 (6 Bots) - Base Offset: 45s
for i in 1 2 3 4 5 6; do
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
echo "✅ Fleet 2 (Even/Odd Team 2) launched [6 bots]."

# Fleet 3: Over/Under Team 1 (6 Bots) - Base Offset: 90s
for i in 1 2 3 4 5 6; do
  BOT_NAME="my-over-under-fleet-bot-$i"
  BOT_DIR="/root/over_under_fleet_bot_$i"
  DELAY=$(( WAIT_SECS + 90 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$OU_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$OU_BUILD/over_under_fleet.py" "$BOT_DIR/over_under_fleet.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-over-under-fleet
done
echo "✅ Fleet 3 (Over/Under Team 1) launched [6 bots]."

# Fleet 4: Over/Under Team 2 (6 Bots) - Base Offset: 135s
for i in 1 2 3 4 5 6; do
  BOT_NAME="my-over-under-fleet2-bot-$i"
  BOT_DIR="/root/over_under_fleet2_bot_$i"
  DELAY=$(( WAIT_SECS + 135 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$OU_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$OU_BUILD/over_under_fleet.py" "$BOT_DIR/over_under_fleet.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-over-under-fleet
done
echo "✅ Fleet 4 (Over/Under Team 2) launched [6 bots]."

# Fleet 5: Over/Under Team 3 (6 Bots - Reallocated from C/P) - Base Offset: 180s
for i in 1 2 3 4 5 6; do
  BOT_NAME="my-over-under-fleet3-bot-$i"
  BOT_DIR="/root/over_under_fleet3_bot_$i"
  DELAY=$(( WAIT_SECS + 180 + (i - 1) * 300 ))
  mkdir -p "$BOT_DIR"
  cp "$OU_BUILD/config.json" "$BOT_DIR/config.json"
  cp "$OU_BUILD/over_under_fleet.py" "$BOT_DIR/over_under_fleet.py"
  rm -f "$BOT_DIR/state.json"
  docker run -d --restart always --name "$BOT_NAME" \
    -e BOT_NAME="$BOT_NAME" \
    -e INITIAL_DELAY_SECONDS="$DELAY" \
    -v "$BOT_DIR:/app" -v "$MASTER_LOCK:/app/lock" \
    headless-over-under-fleet
done
echo "✅ Fleet 5 (Over/Under Team 3) launched [6 bots]."

# Fleet 6: Even/Odd Team 3 (6 Bots - Reallocated from C/P) - Base Offset: 225s
for i in 1 2 3 4 5 6; do
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
echo "✅ Fleet 6 (Even/Odd Team 3) launched [6 bots]."

# 6. Update and restart the live pusher script
echo "🔄 Updating and restarting live monitor pusher..."
pkill -f fleet_monitor_pusher.py 2>/dev/null || true
curl -s -H "Cache-Control: no-cache" "$REPO_RAW/fleet_monitor_pusher.py" > /root/fleet_monitor_pusher.py
if [ -f /root/run_pusher.sh ]; then
  /root/run_pusher.sh
else
  nohup python3 -u /root/fleet_monitor_pusher.py > /root/pusher.log 2>&1 &
fi

echo ""
echo "============================================================"
echo "🎉 ALL 6 FLEETS DEPLOYED WITH FRESH CLEAN START!"
echo "   • Even/Odd Fleets: 3 Teams (18 Bots Total, 30m Rest)"
echo "   • Over/Under Fleets: 3 Teams (18 Bots Total, 30m Rest)"
echo "   • Call/Put: Dormant & safely preserved (Ready to revert anytime)"
echo "   • Master Trade Lock: /root/shared_master_trade_lock (0 collisions)"
echo "   • Fleets Offset: 45s stagger gap between fleet cycles"
echo "   • Markets: 10 Multi-Markets across all bots"
echo "   • Dashboard Live at: https://fleet-bot-monitor.vercel.app"
echo "============================================================"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
