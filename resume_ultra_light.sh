#!/bin/bash
set -e

echo "============================================================"
echo "⚡ SWITCHING TO ULTRA-LIGHT 3-PROCESS ENGINE (KEEPING CURRENT STATE)"
echo "   • RAM Usage drops from ~1,500 MB to ~40 MB total!"
echo "   • Preserves all existing state.json files, profits & recovery stakes"
echo "   • Bybit Fleet: 100% UNTOUCHED"
echo "============================================================"

if ! swapon --show | grep -q "/swapfile_extra"; then
  fallocate -l 1G /swapfile_extra 2>/dev/null || dd if=/dev/zero of=/swapfile_extra bs=1M count=1024 status=none
  chmod 600 /swapfile_extra
  mkswap /swapfile_extra >/dev/null 2>&1 || true
  swapon /swapfile_extra 2>/dev/null || true
fi

echo "🛑 Stopping old 108-process containers to free ~1.4 GB RAM..."
docker ps -aq --filter "name=my-even-odd" --filter "name=my-over-under" --filter "name=my-call-put" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker rm -f acc1-fleet-runner acc2-fleet-runner acc3-fleet-runner >/dev/null 2>&1 || true

pkill -f "run_acc1_fleet" 2>/dev/null || true
pkill -f "run_acc2_fleet" 2>/dev/null || true
pkill -f "run_acc3_fleet" 2>/dev/null || true
pkill -f "even_odd_millipede.py" 2>/dev/null || true
pkill -f "call_put_fleet.py" 2>/dev/null || true

MASTER_LOCK_ACC1="/root/shared_master_trade_lock"
MASTER_LOCK_ACC2="/root/shared_master_trade_lock_acc2"
MASTER_LOCK_ACC3="/root/shared_master_trade_lock_acc3"
mkdir -p "$MASTER_LOCK_ACC1" "$MASTER_LOCK_ACC2" "$MASTER_LOCK_ACC3"
rm -rf "$MASTER_LOCK_ACC1/trade_lock" "$MASTER_LOCK_ACC1/lock_info.json"
rm -rf "$MASTER_LOCK_ACC2/trade_lock" "$MASTER_LOCK_ACC2/lock_info.json"
rm -rf "$MASTER_LOCK_ACC3/trade_lock" "$MASTER_LOCK_ACC3/lock_info.json"

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

cat << 'EOF' > /root/run_acc1_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT91203477"
export DERIV_API_TOKEN="pat_695988b49294981ebda503b4b975f50c6bf826130fe14f5ea25ccea122bcffab"
export SWITCH_MARKET_ON_LOSS="false"
export LOCK_DIR="/root/shared_master_trade_lock"
export STRATEGY_MODE="OVER_UNDER"
export INITIAL_STAKE="0.50"

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

cat << 'EOF' > /root/run_acc2_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT93845070"
export DERIV_API_TOKEN="pat_e8b31d27beb9c0a040f1059ce12bac092383a3838554078c75378bf9831bf955"
export SWITCH_MARKET_ON_LOSS="true"
export LOCK_DIR="/root/shared_master_trade_lock_acc2"
export SINGLE_TRADE_PER_CYCLE="true"
export MAX_TRADES_PER_CYCLE="1"

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

cat << 'EOF' > /root/run_acc3_fleet.sh
#!/bin/bash
export DERIV_ACCOUNT_ID="DOT91362122"
export DERIV_API_TOKEN="pat_6ca0c6bca661b25f102eb309d6748e7fcf423a33138c9b3ed2d7d5605a45f54a"
export SWITCH_MARKET_ON_LOSS="false"
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
echo "✅ Resumed all 108 Deriv bots in 3 Ultra-Light Python processes!"
free -h
