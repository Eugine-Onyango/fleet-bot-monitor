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
GIST_ID = os.getenv("GIST_ID", "e89e6db2da1433214922b69f101e15aa")
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
    # Method 1: Ask Docker for the exact /app mounted host folder
    mount_src = run_cmd(f"docker inspect -f '{{{{range .Mounts}}}}{{{{if eq .Destination \"/app\"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}' {name}")
    if mount_src and os.path.exists(f"{mount_src}/state.json"):
        try:
            with open(f"{mount_src}/state.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Method 2: Fallback to all standard paths
    num = name.split("-")[-1]
    possible_paths = [
        f"/root/over_under_fleet_bot_{num}/state.json",
        f"/root/even_odd_fleet2_bot_{num}/state.json",
        f"/root/even_odd_millipede_bot_{num}/state.json",
        f"/root/over_under_millipede_bot_{num}/state.json",
        f"/root/even_odd_fleet_bot_{num}/state.json",
        f"/root/{name.replace('my-', '').replace('-', '_')}/state.json",
        f"/root/{name}/state.json"
    ]
    
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None

def get_container_uptime(container_name):
    started_raw = run_cmd(f"docker inspect -f '{{{{.State.StartedAt}}}}' {container_name}")
    if not started_raw or "0001-01-01" in started_raw:
        return "0m", 0
    try:
        clean_str = started_raw[:26] + "+00:00" if "T" in started_raw else started_raw
        started_dt = datetime.fromisoformat(clean_str)
        now_dt = datetime.now(timezone.utc)
        elapsed_sec = max(0, int((now_dt - started_dt).total_seconds()))
        days = elapsed_sec // 86400
        hours = (elapsed_sec % 86400) // 3600
        mins = (elapsed_sec % 3600) // 60
        if days > 0:
            short_str = f"{days}d {hours}h {mins}m"
        elif hours > 0:
            short_str = f"{hours}h {mins}m"
        else:
            short_str = f"{mins}m"
        return short_str, elapsed_sec
    except Exception:
        return "0m", 0

def build_payload():
    containers = get_containers()
    
    fleets_dict = {
        "Fleet 2 (Even/Odd)": [],
        "Fleet 1 (Even/Odd)": [],
        "Over/Under Fleet (50/50 Fibonacci)": [],
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
        uptime_str, uptime_sec = get_container_uptime(name)

        bot_profit = 0.0
        wins = 0
        losses = 0
        current_stake = 0.0
        consecutive_losses = 0
        max_stake = 0.35
        max_stake_market = ""
        current_market = ""

        if state_data:
            bot_profit = float(state_data.get("total_profit", state_data.get("profit", 0.0)))
            wins = int(state_data.get("wins", 0))
            losses = int(state_data.get("losses", 0))
            current_stake = float(state_data.get("current_stake", state_data.get("stake", 0.0)))
            consecutive_losses = int(state_data.get("consecutive_losses", 0))
            max_stake = float(state_data.get("max_stake", state_data.get("peak_stake", 0.35)))
            max_stake_market = state_data.get("max_stake_market", "")
            current_market = state_data.get("current_market", "")

        total_profit += bot_profit
        total_wins += wins
        total_losses += losses

        bot_info = {
            "name": name,
            "status": "RUNNING" if is_running else "STOPPED",
            "raw_status": c["status"],
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec,
            "profit": round(bot_profit, 2),
            "wins": wins,
            "losses": losses,
            "current_stake": round(current_stake, 2),
            "consecutive_losses": consecutive_losses,
            "max_stake": round(max_stake, 2),
            "max_stake_market": max_stake_market,
            "current_market": current_market,
            "logs": logs
        }

        # Categorize
        if "fleet2" in name:
            fleets_dict["Fleet 2 (Even/Odd)"].append(bot_info)
        elif "over-under" in name:
            fleets_dict["Over/Under Fleet (50/50 Fibonacci)"].append(bot_info)
        elif "even-odd" in name:
            fleets_dict["Fleet 1 (Even/Odd)"].append(bot_info)
        else:
            fleets_dict["Other Bots"].append(bot_info)

    # Convert to list of populated fleets & calculate fleet peak stakes & uptimes
    fleet_list = []
    overall_peak_stake = 0.0
    overall_peak_market = ""
    overall_max_uptime_sec = 0
    overall_max_uptime_str = "0m"

    for f_name, bots in fleets_dict.items():
        if bots:
            fleet_peak = 0.0
            fleet_market = ""
            fleet_max_sec = 0
            fleet_uptime_str = "0m"

            for b in bots:
                bstake = b.get("max_stake", 0.0)
                bsec = b.get("uptime_seconds", 0)
                if bstake > fleet_peak:
                    fleet_peak = bstake
                    fleet_market = b.get("max_stake_market", "")
                if bstake > overall_peak_stake:
                    overall_peak_stake = bstake
                    overall_peak_market = b.get("max_stake_market", "")
                if bsec > fleet_max_sec:
                    fleet_max_sec = bsec
                    fleet_uptime_str = b.get("uptime", "0m")
                if bsec > overall_max_uptime_sec:
                    overall_max_uptime_sec = bsec
                    overall_max_uptime_str = b.get("uptime", "0m")

            fleet_list.append({
                "fleet_name": f_name,
                "bot_count": len(bots),
                "fleet_peak_stake": round(fleet_peak, 2),
                "fleet_peak_market": fleet_market,
                "fleet_uptime": fleet_uptime_str,
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
        "longest_uptime": overall_max_uptime_str,
        "overall_peak_stake": round(overall_peak_stake, 2),
        "overall_peak_market": overall_peak_market,
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
