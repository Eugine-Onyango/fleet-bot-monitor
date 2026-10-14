import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ================= CONFIGURATION =================
# Replace these with your GitHub Gist details
# You can also pass them via environment variables: GIST_ID and GITHUB_TOKEN
GIST_ID = os.getenv("GIST_ID", "YOUR_GIST_ID_HERE")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
UPDATE_INTERVAL_SECONDS = 30  # Update every 30 seconds
# =================================================

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return ""

def get_containers():
    # List all bot containers matching known fleets
    out = run_cmd("docker ps -a --format '{{.Names}}|{{.Status}}|{{.State}}'")
    containers = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            name, status_str, state = parts[0], parts[1], parts[2]
            # Match our bot prefixes
            if any(k in name for k in ["even-odd", "over-under", "millipede"]):
                containers.append({"name": name, "status": status_str, "state": state})
    return containers

def get_simplified_logs(container_name, lines=25):
    raw_logs = run_cmd(f"docker logs --tail {lines} {container_name} 2>&1")
    simplified = []
    
    # Filter keywords to keep only actionable/meaningful trade log lines
    keep_keywords = [
        "win", "loss", "profit", "stake", "contract", "bought", "purchased",
        "proposal", "balance", "cycle", "cooldown", "payout", "error", "starting",
        "waiting", "stagger", "delay", "even", "odd", "over", "under"
    ]
    
    for line in raw_logs.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        # Check if line contains any interesting trade keyword
        lower_line = line_clean.lower()
        if any(kw in lower_line for kw in keep_keywords) or len(raw_logs.splitlines()) <= 8:
            # Clean up escape codes / messy symbols
            if len(line_clean) > 160:
                line_clean = line_clean[:157] + "..."
            simplified.append(line_clean)
            
    return simplified[-15:] if simplified else ["No recent trade events recorded yet."]

def get_bot_state(name):
    # Try finding associated state.json on disk
    possible_paths = [
        f"/root/{name.replace('my-', '').replace('-', '_')}/state.json",
        f"/root/even_odd_fleet2_bot_{name.split('-')[-1]}/state.json",
        f"/root/even_odd_fleet_bot_{name.split('-')[-1]}/state.json",
        f"/root/over_under_millipede_bot_{name.split('-')[-1]}/state.json"
    ]
    
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None

def build_payload():
    containers = get_containers()
    
    fleets_dict = {
        "Fleet 2 (Even/Odd)": [],
        "Fleet 1 (Even/Odd)": [],
        "Over/Under Fleet": [],
        "Other Bots": []
    }
    
    total_profit = 0.0
    total_wins = 0
    total_losses = 0
    total_active_bots = 0

    for c in containers:
        name = c["name"]
        is_running = (c["state"].lower() == "running")
        if is_running:
            total_active_bots += 1

        state_data = get_bot_state(name)
        logs = get_simplified_logs(name)

        bot_profit = 0.0
        wins = 0
        losses = 0
        current_stake = 0.0
        consecutive_losses = 0

        if state_data:
            bot_profit = float(state_data.get("total_profit", state_data.get("profit", 0.0)))
            wins = int(state_data.get("wins", 0))
            losses = int(state_data.get("losses", 0))
            current_stake = float(state_data.get("current_stake", state_data.get("stake", 0.0)))
            consecutive_losses = int(state_data.get("consecutive_losses", 0))

        total_profit += bot_profit
        total_wins += wins
        total_losses += losses

        bot_info = {
            "name": name,
            "status": "RUNNING" if is_running else "STOPPED",
            "raw_status": c["status"],
            "profit": round(bot_profit, 2),
            "wins": wins,
            "losses": losses,
            "current_stake": round(current_stake, 2),
            "consecutive_losses": consecutive_losses,
            "logs": logs
        }

        # Categorize
        if "fleet2" in name:
            fleets_dict["Fleet 2 (Even/Odd)"].append(bot_info)
        elif "even-odd" in name:
            fleets_dict["Fleet 1 (Even/Odd)"].append(bot_info)
        elif "over-under" in name:
            fleets_dict["Over/Under Fleet"].append(bot_info)
        else:
            fleets_dict["Other Bots"].append(bot_info)

    # Convert to list of populated fleets
    fleet_list = []
    for f_name, bots in fleets_dict.items():
        if bots:
            fleet_list.append({
                "fleet_name": f_name,
                "bot_count": len(bots),
                "bots": sorted(bots, key=lambda x: x["name"])
            })

    total_trades = total_wins + total_losses
    win_rate = round((total_wins / total_trades * 100), 1) if total_trades > 0 else 0.0

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_active_bots": total_active_bots,
        "total_containers": len(containers),
        "total_profit": round(total_profit, 2),
        "total_wins": total_wins,
        "total_losses": total_losses,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "fleets": fleet_list
    }

def push_to_gist(payload):
    if not GIST_ID or GIST_ID == "YOUR_GIST_ID_HERE":
        print("[!] GIST_ID not configured! Please provide your Gist ID.")
        return False
    if not GITHUB_TOKEN or GITHUB_TOKEN == "YOUR_GITHUB_TOKEN_HERE":
        print("[!] GITHUB_TOKEN not configured! Please provide your GitHub Personal Access Token.")
        return False

    url = f"https://api.github.com/gists/{GIST_ID}"
    body = {
        "description": f"Fleet Bots Live Status - Updated {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}",
        "files": {
            "fleet_status.json": {
                "content": json.dumps(payload, indent=2)
            }
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "Fleet-Bot-Pusher/1.0"
        },
        method="PATCH"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in [200, 201]:
                return True
            else:
                print(f"[!] Push failed with status {resp.status}")
                return False
    except urllib.error.HTTPError as e:
        print(f"[!] HTTP error: {e.code} - {e.read().decode('utf-8', errors='replace')}")
        return False
    except Exception as e:
        print(f"[!] Connection error: {e}")
        return False

def main():
    print("=" * 60)
    print("🚀 FLEET BOTS LIVE MONITOR PUSHER STARTED")
    print(f"Target Gist ID: {GIST_ID}")
    print(f"Update Interval: {UPDATE_INTERVAL_SECONDS} seconds")
    print("=" * 60)

    while True:
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            payload = build_payload()
            success = push_to_gist(payload)
            if success:
                print(f"[{now_str}] ✅ Pushed fleet status: {payload['total_active_bots']} bots active | P/L: ${payload['total_profit']} | {payload['win_rate']}% WR")
            else:
                print(f"[{now_str}] ⚠️ Failed to update Gist.")
        except Exception as e:
            print(f"[!] Loop error: {e}")

        time.sleep(UPDATE_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
