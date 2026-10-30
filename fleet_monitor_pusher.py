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
UPDATE_INTERVAL_SECONDS = 45  # Update every 30 seconds
# =================================================

PEAK_FILE = os.getenv("PEAK_FILE", "/root/fleet_peak_profits.json" if os.name != "nt" else "fleet_peak_profits.json")

def load_peaks():
    if os.path.exists(PEAK_FILE):
        try:
            with open(PEAK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"overall": 0.0, "systems": {"eo": 0.0, "ou": 0.0, "cp": 0.0}, "fleets": {}, "bots": {}}

def save_peaks(peaks):
    try:
        with open(PEAK_FILE, "w", encoding="utf-8") as f:
            json.dump(peaks, f, indent=2)
    except Exception:
        pass

def run_cmd(cmd, timeout_sec=20):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_sec)
        return res.stdout.strip()
    except Exception as e:
        return ""

def resolve_bot_dir(name):
    num = name.split("-")[-1]
    if name.startswith("acc2-"):
        if "even-odd-fleet3" in name: return f"/root/acc2_even_odd_fleet3_bot_{num}"
        if "even-odd-fleet2" in name: return f"/root/acc2_even_odd_fleet2_bot_{num}"
        if "even-odd-bot" in name: return f"/root/acc2_even_odd_millipede_bot_{num}"
        if "over-under-fleet3" in name: return f"/root/acc2_over_under_fleet3_bot_{num}"
        if "over-under-fleet2" in name: return f"/root/acc2_over_under_fleet2_bot_{num}"
        if "over-under-fleet" in name: return f"/root/acc2_over_under_fleet_bot_{num}"
    elif name.startswith("acc3-"):
        if "even-odd-fleet3" in name: return f"/root/acc3_even_odd_fleet3_bot_{num}"
        if "even-odd-fleet2" in name: return f"/root/acc3_even_odd_fleet2_bot_{num}"
        if "even-odd-bot" in name: return f"/root/acc3_even_odd_millipede_bot_{num}"
        if "over-under-fleet3" in name: return f"/root/acc3_over_under_fleet3_bot_{num}"
        if "over-under-fleet2" in name: return f"/root/acc3_over_under_fleet2_bot_{num}"
        if "over-under-fleet" in name: return f"/root/acc3_over_under_fleet_bot_{num}"
    else:
        if "bybit" in name: return f"/root/bybit_fleet_bot_{num}"
        if "even-odd-fleet3" in name: return f"/root/even_odd_fleet3_bot_{num}"
        if "even-odd-fleet2" in name: return f"/root/even_odd_fleet2_bot_{num}"
        if "even-odd-bot" in name: return f"/root/even_odd_millipede_bot_{num}"
        if "over-under-fleet3" in name: return f"/root/over_under_fleet3_bot_{num}"
        if "over-under-fleet2" in name: return f"/root/over_under_fleet2_bot_{num}"
        if "over-under-fleet" in name: return f"/root/over_under_fleet_bot_{num}"
        if "call-put-fleet2" in name: return f"/root/call_put_fleet2_bot_{num}"
        if "call-put-fleet" in name: return f"/root/call_put_fleet_bot_{num}"
    return f"/root/{name.replace('-', '_')}"

def get_containers():
    containers = []
    seen_names = set()

    # 1. List Docker containers (Account 1 & Bybit)
    out = run_cmd("docker ps -a --format '{{.Names}}|{{.Status}}|{{.State}}'", timeout_sec=20)
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            name, status_str, state = parts[0], parts[1], parts[2]
            if any(k in name for k in ["even-odd", "over-under", "call-put", "millipede", "bybit"]):
                containers.append({
                    "name": name,
                    "status": status_str,
                    "state": state,
                    "is_native": False,
                    "dir": resolve_bot_dir(name)
                })
                seen_names.add(name)

    # 2. Discover lightweight native bots (Account 1, 2, and 3)
    if os.path.exists("/root"):
        try:
            for entry in sorted(os.listdir("/root")):
                if any(entry.startswith(prefix) for prefix in ["acc1_", "acc2_", "acc3_", "even_odd_", "over_under_", "call_put_"]):
                    bot_dir = os.path.join("/root", entry)
                    meta_path = os.path.join(bot_dir, "bot_meta.json")
                    if os.path.isdir(bot_dir) and os.path.exists(meta_path):
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            b_name = meta.get("name", "")
                            if b_name and b_name not in seen_names:
                                pid = meta.get("pid", 0)
                                is_alive = bool(pid and os.path.exists(f"/proc/{pid}"))
                                started_ts = float(meta.get("started_at", time.time()))
                                elapsed = max(0, int(time.time() - started_ts))
                                containers.append({
                                    "name": b_name,
                                    "status": f"Up {elapsed // 60} minutes",
                                    "state": "running" if is_alive else "stopped",
                                    "is_native": True,
                                    "dir": bot_dir,
                                    "started_at": started_ts
                                })
                                seen_names.add(b_name)
                        except Exception:
                            pass
        except Exception:
            pass

    return containers

def get_simplified_logs(c_obj, lines=25):
    container_name = c_obj["name"]
    bot_dir = c_obj.get("dir") or resolve_bot_dir(container_name)
    raw_logs = ""

    # Fast path: read directly from bot.log if present (0ms, zero Docker load)
    log_file = os.path.join(bot_dir, "bot.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 8192), os.SEEK_SET)
                raw_logs = f.read().decode("utf-8", errors="replace")
        except Exception:
            raw_logs = ""

    if not raw_logs and not c_obj.get("is_native"):
        raw_logs = run_cmd(f"docker logs --tail {lines} {container_name} 2>&1", timeout_sec=8)

    simplified = []
    keep_keywords = [
        "win", "loss", "profit", "stake", "contract", "bought", "purchased",
        "proposal", "balance", "cycle", "cooldown", "payout", "error", "starting",
        "waiting", "stagger", "delay", "even", "odd", "over", "under", "call", "put",
        "rise", "fall", "trend", "queue", "lock", "long", "short", "bybit", "placing", "settled", "pnl", "switch"
    ]
    
    all_lines = raw_logs.splitlines()[-lines:]
    for line in all_lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        lower_line = line_clean.lower()
        if any(kw in lower_line for kw in keep_keywords) or len(all_lines) <= 8:
            if len(line_clean) > 160:
                line_clean = line_clean[:157] + "..."
            simplified.append(line_clean)
            
    return simplified[-15:] if simplified else ["No recent trade events recorded yet."]

def get_bot_state(c_obj):
    name = c_obj["name"]
    bot_dir = c_obj.get("dir") or resolve_bot_dir(name)

    # Fast path: check mapped directory directly (0ms, no docker inspect needed!)
    direct_state = os.path.join(bot_dir, "state.json")
    if os.path.exists(direct_state):
        try:
            with open(direct_state, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback paths
    num = name.split("-")[-1]
    possible_paths = [
        f"/root/{name.replace('-', '_')}/state.json",
        f"/root/bybit_fleet_bot_{num}/state.json",
        f"/root/even_odd_fleet3_bot_{num}/state.json",
        f"/root/over_under_fleet3_bot_{num}/state.json",
        f"/root/call_put_fleet_bot_{num}/state.json",
        f"/root/call_put_fleet2_bot_{num}/state.json",
        f"/root/over_under_fleet_bot_{num}/state.json",
        f"/root/over_under_fleet2_bot_{num}/state.json",
        f"/root/even_odd_fleet2_bot_{num}/state.json",
        f"/root/even_odd_millipede_bot_{num}/state.json",
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

def get_container_uptime(c_obj):
    # 1. If native bot with started_at timestamp, compute exact uptime in 0ms
    if c_obj.get("started_at"):
        elapsed_sec = max(0, int(time.time() - float(c_obj["started_at"])))
    else:
        # 2. Parse Docker status string (e.g. "Up 4 hours", "Up 25 minutes", "Up 2 days") in 0ms
        status_str = c_obj.get("status", "").lower()
        elapsed_sec = 0
        import re
        if "about an hour" in status_str:
            elapsed_sec = 3600
        elif "about a minute" in status_str:
            elapsed_sec = 60
        else:
            m_days = re.search(r'(\d+)\s*day', status_str)
            m_hrs = re.search(r'(\d+)\s*hour', status_str)
            m_mins = re.search(r'(\d+)\s*minute', status_str)
            m_secs = re.search(r'(\d+)\s*second', status_str)
            if m_days: elapsed_sec += int(m_days.group(1)) * 86400
            if m_hrs: elapsed_sec += int(m_hrs.group(1)) * 3600
            if m_mins: elapsed_sec += int(m_mins.group(1)) * 60
            if m_secs: elapsed_sec += int(m_secs.group(1))

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

def build_payload():
    containers = get_containers()
    peaks = load_peaks()
    if "systems" not in peaks:
        peaks["systems"] = {"eo": 0.0, "ou": 0.0, "cp": 0.0, "bybit": 0.0}
    if "account_systems" not in peaks:
        peaks["account_systems"] = {}
    if "account_fleets" not in peaks:
        peaks["account_fleets"] = {}
    if "fleets" not in peaks:
        peaks["fleets"] = {}
    if "bots" not in peaks:
        peaks["bots"] = {}
    
    fleets_dict = {
        "Fleet 1 (Even/Odd)": [],
        "Fleet 2 (Even/Odd)": [],
        "Fleet 3 (Even/Odd)": [],
        "Fleet 1 (Over/Under)": [],
        "Fleet 2 (Over/Under)": [],
        "Fleet 3 (Over/Under)": [],
        "Fleet 1 (Call/Put)": [],
        "Fleet 2 (Call/Put)": [],
        "Fleet 1 (Bybit)": [],
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

        if name.startswith("acc2-"):
            account = "acc2"
        elif name.startswith("acc3-"):
            account = "acc3"
        elif "bybit" in name:
            account = "bybit"
        else:
            account = "acc1"

        state_data = get_bot_state(c)
        logs = get_simplified_logs(c)
        uptime_str, uptime_sec = get_container_uptime(c)

        default_stake = 0.35
        bot_profit = 0.0
        wins = 0
        losses = 0
        current_stake = default_stake
        consecutive_losses = 0
        max_stake = default_stake
        max_stake_market = ""
        current_market = ""

        if state_data:
            bot_profit = float(state_data.get("total_profit", state_data.get("profit", 0.0)))
            wins = int(state_data.get("wins", 0))
            losses = int(state_data.get("losses", 0))
            current_stake = float(state_data.get("current_stake", state_data.get("cycle_stake", state_data.get("stake", default_stake))))
            consecutive_losses = int(state_data.get("consecutive_losses", state_data.get("consecutive_cycle_losses", 0)))
            max_stake = float(state_data.get("max_stake", state_data.get("peak_stake", default_stake)))
            max_stake_market = state_data.get("max_stake_market", "")
            current_market = state_data.get("current_market", "") or ""

        bot_profit_val = round(bot_profit, 2)
        if (wins + losses) == 0:
            b_peak = bot_profit_val
            peaks["bots"][name] = bot_profit_val
        else:
            b_peak = max(peaks["bots"].get(name, 0.0), bot_profit_val)
            peaks["bots"][name] = b_peak
        b_drawdown = max(0.0, round(b_peak - bot_profit_val, 2))

        total_profit += bot_profit
        total_wins += wins
        total_losses += losses

        bot_info = {
            "name": name,
            "account": account,
            "status": "RUNNING" if is_running else "STOPPED",
            "raw_status": c["status"],
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec,
            "profit": bot_profit_val,
            "peak_profit": b_peak,
            "profit_drawdown": b_drawdown,
            "wins": wins,
            "losses": losses,
            "current_stake": round(current_stake, 2),
            "consecutive_losses": consecutive_losses,
            "max_stake": round(max_stake, 2),
            "max_stake_market": max_stake_market,
            "current_market": current_market,
            "logs": logs
        }

        # Categorize into distinct fleets
        if "bybit" in name:
            fleets_dict["Fleet 1 (Bybit)"].append(bot_info)
        elif "even-odd" in name:
            if "fleet3" in name:
                fleets_dict["Fleet 3 (Even/Odd)"].append(bot_info)
            elif "fleet2" in name:
                fleets_dict["Fleet 2 (Even/Odd)"].append(bot_info)
            else:
                fleets_dict["Fleet 1 (Even/Odd)"].append(bot_info)
        elif "over-under" in name:
            if "fleet3" in name:
                fleets_dict["Fleet 3 (Over/Under)"].append(bot_info)
            elif "fleet2" in name:
                fleets_dict["Fleet 2 (Over/Under)"].append(bot_info)
            else:
                fleets_dict["Fleet 1 (Over/Under)"].append(bot_info)
        elif "call-put" in name:
            if "fleet2" in name:
                fleets_dict["Fleet 2 (Call/Put)"].append(bot_info)
            else:
                fleets_dict["Fleet 1 (Call/Put)"].append(bot_info)
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
            def bot_sort_key(b):
                parts = b.get("name", "").split("-")
                num_val = int(parts[-1]) if parts[-1].isdigit() else 999
                return (b.get("account", "acc1"), num_val)
            bots.sort(key=bot_sort_key)
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

            # Track per-account fleet peaks
            acc_fleet_peaks = {}
            for acc_key in ["acc1", "acc2", "acc3", "bybit"]:
                acc_bots = [b for b in bots if b.get("account", "acc1") == acc_key]
                if acc_bots:
                    acc_f_trades = sum(b.get("wins", 0) + b.get("losses", 0) for b in acc_bots)
                    acc_f_profit = round(sum(b["profit"] for b in acc_bots), 2)
                    pk_key = f"{acc_key}_{f_name}"
                    if acc_f_trades == 0:
                        acc_f_peak = acc_f_profit
                        peaks["account_fleets"][pk_key] = acc_f_profit
                    else:
                        acc_f_peak = max(peaks["account_fleets"].get(pk_key, 0.0), acc_f_profit)
                        peaks["account_fleets"][pk_key] = acc_f_peak
                    acc_fleet_peaks[acc_key] = acc_f_peak

            # Legacy fleet peak (using acc1 or bybit so Account 1 stays accurate)
            acc1_or_bybit_bots = [b for b in bots if b.get("account", "acc1") in ("acc1", "bybit")]
            target_f_bots = acc1_or_bybit_bots if acc1_or_bybit_bots else bots
            fleet_trades = sum(b.get("wins", 0) + b.get("losses", 0) for b in target_f_bots)
            fleet_profit_val = round(sum(b["profit"] for b in target_f_bots), 2)
            if fleet_trades == 0:
                f_peak = fleet_profit_val
                peaks["fleets"][f_name] = fleet_profit_val
            else:
                f_peak = max(peaks["fleets"].get(f_name, 0.0), fleet_profit_val)
                peaks["fleets"][f_name] = f_peak
            f_drawdown = max(0.0, round(f_peak - fleet_profit_val, 2))

            fleet_list.append({
                "fleet_name": f_name,
                "bot_count": len(bots),
                "fleet_profit": fleet_profit_val,
                "fleet_peak_profit": f_peak,
                "fleet_profit_drawdown": f_drawdown,
                "account_peaks": acc_fleet_peaks,
                "fleet_peak_stake": round(fleet_peak, 2),
                "fleet_peak_market": fleet_market,
                "fleet_uptime": fleet_uptime_str,
                "bots": bots
            })

    # System totals and peaks (Per Account & Legacy)
    all_eo_bots = fleets_dict.get("Fleet 1 (Even/Odd)", []) + fleets_dict.get("Fleet 2 (Even/Odd)", [])
    all_ou_bots = fleets_dict.get("Fleet 1 (Over/Under)", []) + fleets_dict.get("Fleet 2 (Over/Under)", [])
    all_cp_bots = fleets_dict.get("Fleet 3 (Over/Under)", []) + fleets_dict.get("Fleet 3 (Even/Odd)", [])
    if not all_cp_bots:
        all_cp_bots = fleets_dict.get("Fleet 1 (Call/Put)", []) + fleets_dict.get("Fleet 2 (Call/Put)", [])
    bybit_bots = fleets_dict.get("Fleet 1 (Bybit)", [])

    for acc_key in ["acc1", "acc2", "acc3"]:
        a_eo = [b for b in all_eo_bots if b.get("account", "acc1") == acc_key]
        a_ou = [b for b in all_ou_bots if b.get("account", "acc1") == acc_key]
        a_cp = [b for b in all_cp_bots if b.get("account", "acc1") == acc_key]
        a_all = a_eo + a_ou + a_cp

        for sys_name, sys_bots in [("eo", a_eo), ("ou", a_ou), ("cp", a_cp), ("all", a_all)]:
            p_val = round(sum(b["profit"] for b in sys_bots), 2)
            t_val = sum(b.get("wins", 0) + b.get("losses", 0) for b in sys_bots)
            k = f"{acc_key}_{sys_name}"
            if t_val == 0:
                peaks["account_systems"][k] = 0.0
            else:
                peaks["account_systems"][k] = max(peaks["account_systems"].get(k, 0.0), p_val)

    # Keep peaks["systems"] synced to Account 1 + Bybit
    peaks["systems"]["eo"] = peaks["account_systems"].get("acc1_eo", 0.0)
    peaks["systems"]["ou"] = peaks["account_systems"].get("acc1_ou", 0.0)
    peaks["systems"]["cp"] = peaks["account_systems"].get("acc1_cp", 0.0)

    bybit_profit = round(sum(b["profit"] for b in bybit_bots), 2)
    bybit_trades = sum(b.get("wins", 0) + b.get("losses", 0) for b in bybit_bots)
    if bybit_trades == 0:
        peaks["systems"]["bybit"] = 0.0
    else:
        peaks["systems"]["bybit"] = max(peaks["systems"].get("bybit", 0.0), bybit_profit)

    eo_profit = round(sum(b["profit"] for b in all_eo_bots if b.get("account", "acc1") == "acc1"), 2)
    ou_profit = round(sum(b["profit"] for b in all_ou_bots if b.get("account", "acc1") == "acc1"), 2)
    cp_profit = round(sum(b["profit"] for b in all_cp_bots if b.get("account", "acc1") == "acc1"), 2)

    total_trades = total_wins + total_losses
    win_rate = round((total_wins / total_trades * 100), 1) if total_trades > 0 else 0.0

    if total_trades == 0:
        overall_peak = 0.0
        peaks["overall"] = 0.0
    else:
        overall_peak = max(peaks.get("overall", 0.0), round(total_profit, 2))
        peaks["overall"] = overall_peak

    save_peaks(peaks)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reset_at": peaks.get("reset_at", datetime.now(timezone.utc).isoformat()),
        "total_active_bots": total_active_bots,
        "total_containers": len(containers),
        "total_profit": round(total_profit, 2),
        "overall_peak_profit": overall_peak,
        "overall_profit_drawdown": max(0.0, round(overall_peak - round(total_profit, 2), 2)),
        "account_system_peaks": peaks["account_systems"],
        "system_peak_profits": {
            "eo": peaks["systems"]["eo"],
            "ou": peaks["systems"]["ou"],
            "cp": peaks["systems"]["cp"],
            "bybit": peaks["systems"]["bybit"]
        },
        "system_profit_drawdowns": {
            "eo": max(0.0, round(peaks["systems"]["eo"] - eo_profit, 2)),
            "ou": max(0.0, round(peaks["systems"]["ou"] - ou_profit, 2)),
            "cp": max(0.0, round(peaks["systems"]["cp"] - cp_profit, 2)),
            "bybit": max(0.0, round(peaks["systems"]["bybit"] - bybit_profit, 2))
        },
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
            if payload.get("total_containers", 0) == 0:
                print(f"[{now_str}] ⚠️ 0 containers detected (Docker busy?), skipping Gist overwrite.")
                time.sleep(UPDATE_INTERVAL_SECONDS)
                continue
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
