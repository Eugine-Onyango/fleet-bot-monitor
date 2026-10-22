import json
import time
import os
import sys
import datetime
import threading
import random
import requests
import websocket

# Reconfigure standard streams for UTF-8 stability
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

LOCK_DIR = os.getenv("LOCK_DIR", "/app/lock")
LOCK_PATH = os.path.join(LOCK_DIR, "trade_lock")
INFO_FILE = os.path.join(LOCK_DIR, "lock_info.json")
BOT_NAME = os.getenv("BOT_NAME", "my-call-put-fleet-bot-1")

UPTIME_OFFSET_SECONDS = int(os.getenv("UPTIME_OFFSET_SECONDS", "0"))
START_TIME = time.time()

def get_uptime_string():
    elapsed = (time.time() - START_TIME) + UPTIME_OFFSET_SECONDS
    days = int(elapsed // 86400)
    hours = int((elapsed % 86400) // 3600)
    minutes = int((elapsed % 3600) // 60)
    if days > 0:
        return f"{days} days, {hours} hours, {minutes} minutes"
    elif hours > 0:
        return f"{hours} hours, {minutes} minutes"
    return f"{minutes} minutes"

def is_valid_hybrid_sequence(seq):
    if not isinstance(seq, list) or len(seq) < 2:
        return False
    eo_types = {"DIGITEVEN", "DIGITODD"}
    cp_types = {"CALL", "PUT"}
    s1, s2 = seq[0], seq[1]
    return (s1 in eo_types and s2 in cp_types) or (s1 in cp_types and s2 in eo_types)

def generate_paired_sequence(dominant_eo=None, dominant_cp=None, first_family=None):
    # Family 1: Even / Odd
    if dominant_eo in ("DIGITEVEN", "DIGITODD"):
        eo = dominant_eo
    else:
        eo = random.choice(["DIGITEVEN", "DIGITODD"])
        
    # Family 2: Call / Put
    if dominant_cp in ("CALL", "PUT"):
        cp = dominant_cp
    else:
        cp = random.choice(["CALL", "PUT"])
        
    # Cross-family pairing: exactly one from each family
    if first_family == "EO":
        return [eo, cp]
    elif first_family == "CP":
        return [cp, eo]
    else:
        return [eo, cp] if random.random() < 0.5 else [cp, eo]

def get_side_description(contract_type):
    if contract_type == "CALL":
        return "Rise (Bullish)"
    elif contract_type == "PUT":
        return "Fall (Bearish)"
    elif contract_type == "DIGITEVEN":
        return "Digit Even"
    elif contract_type == "DIGITODD":
        return "Digit Odd"
    return contract_type

CONFIG = {}
STATE = {
    "total_profit": 0.0,
    "wins": 0,
    "losses": 0,
    "current_market": None,
    "in_recovery": False,
    "market_basket": [],
    "market_index": 0,
    "cycle_profit": 0.0,
    "cycle_stake": 0.35,
    "consecutive_cycle_losses": 0,
    "max_stake": 0.35,
    "max_stake_market": "N/A",
    "max_drawdown": 0.0,
    "max_cycle_loss": 0.0,
    "trade_timestamps": [],
    "markets_state": {}
}
state_lock = threading.RLock()

# Trade session variables managed within run_trade_cycle
cycle_step = 1  # 1 to 2
active_proposal_id = None
active_contract_id = None
trade_completed_event = threading.Event()
ws_connection = None
is_trade_active = False
halted = False
last_cycle_won = False
scanner_results = {}
scanner_targets = []

def load_config(verbose=False):
    global CONFIG
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                CONFIG = json.load(f)
            # Support environment variable overrides for multi-account testing
            if os.getenv("DERIV_API_TOKEN"):
                CONFIG["api_token"] = os.getenv("DERIV_API_TOKEN")
            if os.getenv("DERIV_ACCOUNT_ID"):
                CONFIG["account_id"] = os.getenv("DERIV_ACCOUNT_ID")
            if os.getenv("SWITCH_MARKET_ON_LOSS"):
                CONFIG["switch_market_on_loss"] = os.getenv("SWITCH_MARKET_ON_LOSS").lower() in ("1", "true", "yes")
            if verbose:
                safe_cfg = dict(CONFIG)
                if "api_token" in safe_cfg:
                    safe_cfg["api_token"] = safe_cfg["api_token"][:10] + "..."
                print(f"[SYSTEM] Loaded config: {json.dumps(safe_cfg, indent=2)}")
        else:
            print(f"[ERROR] Config file {CONFIG_FILE} not found!")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}")
        sys.exit(1)

def refill_market_basket():
    disabled = set(CONFIG.get("disabled_markets", []))
    all_markets = [m for m in CONFIG.get("markets", []) if m not in disabled]
    if not all_markets:
        all_markets = ["1HZ10V"]
    random.shuffle(all_markets)
    STATE["market_basket"] = all_markets
    print(f"🧺 [BASKET REFILL] Basket refilled with {len(all_markets)} Call/Put markets: {STATE['market_basket']}")
    return STATE["market_basket"]

def advance_market_on_win():
    curr = STATE.get("current_market")
    basket = STATE.get("market_basket", [])
    if curr in basket:
        basket.remove(curr)
    if not basket:
        print(f"🎉 [BASKET COMPLETED] All Call/Put markets in basket completed! Refilling fresh basket!")
        refill_market_basket()
    else:
        print(f"🎉 [BASKET ADVANCE] Profit made on {curr}! Remaining in basket ({len(basket)}): {basket}")
    STATE["current_market"] = None
    STATE["in_recovery"] = False
    return STATE.get("market_basket", [None])[0]

def advance_market_on_loss():
    curr = STATE.get("current_market")
    basket = STATE.get("market_basket", [])
    if curr in basket:
        basket.remove(curr)
    if not basket:
        print(f"🔄 [BASKET COMPLETED ON LOSS] Refilling fresh basket for Market-Switch Recovery!")
        refill_market_basket()
        # Ensure we don't immediately re-pick the exact same losing market if possible
        if len(STATE["market_basket"]) > 1 and curr in STATE["market_basket"]:
            STATE["market_basket"].remove(curr)
    else:
        print(f"🔄 [MARKET SWITCH ON LOSS] Leaving {curr} after 2-step loss! Remaining in basket ({len(basket)}): {basket}")
    STATE["current_market"] = None
    STATE["in_recovery"] = False
    return STATE.get("market_basket", [None])[0]

def load_state(verbose=False):
    global STATE
    with state_lock:
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    STATE.update(loaded)
                if verbose:
                    print(f"[SYSTEM] Loaded state: {json.dumps(STATE, indent=2)}")
            else:
                if verbose:
                    print("[SYSTEM] No state file found. Initializing new state.")
                if not STATE.get("market_basket"):
                    refill_market_basket()
                save_state_unlocked()
        except Exception as e:
            print(f"[ERROR] Failed to load state: {e}")

def save_state_unlocked():
    try:
        if "markets_state" not in STATE:
            STATE["markets_state"] = {}
        markets = CONFIG.get("markets", [])
        for m in markets:
            if m not in STATE["markets_state"]:
                STATE["markets_state"][m] = {
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0.0,
                    "sequence": generate_paired_sequence(),
                    "payout_rates": {}
                }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to save state: {e}")

def get_otp_ws_url():
    url = f"https://api.derivws.com/trading/v1/options/accounts/{CONFIG['account_id']}/otp"
    headers = {
        "Deriv-App-ID": str(CONFIG["app_id"]),
        "Authorization": f"Bearer {CONFIG['api_token']}"
    }
    try:
        res = requests.post(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()['data']['url']
        elif res.status_code == 429:
            retry_after = int(res.headers.get("Retry-After", "60"))
            print(f"⚠️ [RATE LIMIT 429] Deriv requested a pause. Backing off for {retry_after}s...")
            time.sleep(min(retry_after, 120))
            return None
        else:
            print(f"[OTP ERROR] Status: {res.status_code}, Response: {res.text[:120]}")
            return None
    except Exception as e:
        print(f"[OTP EXCEPTION] {e}")
        return None

def send_proposal(ws, contract_type, stake):
    current_market = STATE.get("current_market")
    
    req = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": "USD",
        "duration": CONFIG.get("trade_duration", 1),
        "duration_unit": CONFIG.get("duration_unit", "t"),
        "underlying_symbol": current_market
    }
    with state_lock:
        if stake > STATE.get("max_stake", 0.0) or not STATE.get("max_stake_market"):
            STATE["max_stake"] = stake
            STATE["max_stake_market"] = current_market
        save_state_unlocked()

    side_desc = get_side_description(contract_type)
    print(f"   • [Trade {cycle_step}/2] Requesting {contract_type} ({side_desc}) on {current_market} @ ${stake:.2f}...")
    ws.send(json.dumps(req))

def send_buy(ws, proposal_id, stake):
    req = {"buy": proposal_id, "price": stake}
    print(f"   • Executing Buy for Proposal ID: {proposal_id} @ ${stake:.2f}...")
    ws.send(json.dumps(req))

def on_message(ws, message):
    global active_proposal_id, active_contract_id, cycle_step, last_cycle_won, scanner_results, scanner_targets
    data = json.loads(message)
    msg_type = data.get("msg_type")

    if "error" in data:
        err = data["error"]
        req_sym = data.get("echo_req", {}).get("ticks_history")
        if req_sym and req_sym in scanner_targets:
            print(f"[SCANNER SKIP] {req_sym} unavailable ({err.get('message')}). Removing from active scan.")
            scanner_targets.remove(req_sym)
            if len(scanner_results) >= len(scanner_targets) and len(scanner_results) > 0:
                pass
            else:
                return
        else:
            print(f"[API ERROR] Code: {err.get('code')}, Msg: {err.get('message')}")
            trade_completed_event.set()
            ws.close()
            return

    # Handle live scanner tick history responses for Hybrid E/O and Call/Put
    if "history" in data or (len(scanner_targets) > 0 and len(scanner_results) >= len(scanner_targets) and (STATE.get("current_market") is None or STATE.get("in_recovery", False))):
        if "history" in data:
            sym = data.get("echo_req", {}).get("ticks_history")
            prices = data["history"].get("prices", [])
            pip_size = int(data.get("pip_size", 3))
            
            if prices and len(prices) >= 2:
                # 1. Even / Odd digit distribution
                evens = 0
                odds = 0
                for p in prices:
                    s = f"{p:.{pip_size}f}"
                    d_val = int(s[-1])
                    if d_val % 2 == 0:
                        evens += 1
                    else:
                        odds += 1
                total_digits = len(prices)
                dominant_eo = "DIGITEVEN" if evens >= odds else "DIGITODD"
                eo_pct = (max(evens, odds) / total_digits) * 100
                eo_bias = abs(evens - odds) / total_digits

                # 2. Call / Put momentum & trend
                start_p = float(prices[0])
                end_p = float(prices[-1])
                max_p = max(prices)
                min_p = min(prices)
                rng = max_p - min_p if max_p != min_p else 1.0

                up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
                down_moves = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
                total_moves = up_moves + down_moves if (up_moves + down_moves) > 0 else 1

                is_up = end_p >= start_p
                dominant_cp = "CALL" if is_up else "PUT"
                cp_momentum = (up_moves / total_moves) if is_up else (down_moves / total_moves)
                cp_pct = cp_momentum * 100
                cp_bias = (abs(end_p - start_p) / rng) * 0.5 + (cp_momentum - 0.5) * 0.5

                overall_score = eo_bias + max(0.0, cp_bias)

                # Prioritize stronger family for Trade 1
                if eo_pct >= cp_pct:
                    pair_sequence = [dominant_eo, dominant_cp]
                    order_desc = f"{dominant_eo} ({eo_pct:.1f}%) > {dominant_cp} ({cp_pct:.1f}%)"
                else:
                    pair_sequence = [dominant_cp, dominant_eo]
                    order_desc = f"{dominant_cp} ({cp_pct:.1f}%) > {dominant_eo} ({eo_pct:.1f}%)"

                scanner_results[sym] = {
                    "score": overall_score,
                    "sequence": pair_sequence,
                    "dominant_eo": dominant_eo,
                    "dominant_cp": dominant_cp,
                    "eo_pct": eo_pct,
                    "cp_pct": cp_pct,
                    "order_desc": order_desc
                }
        
        # When all targets are scanned, pick #1 best hybrid market and proceed to trade
        if len(scanner_results) >= len(scanner_targets) and len(scanner_results) > 0:
            sorted_mkts = sorted(scanner_results.items(), key=lambda x: x[1]['score'], reverse=True)
            best_sym, best_data = sorted_mkts[0]
            
            with state_lock:
                STATE["current_market"] = best_sym
                market_state = STATE["markets_state"].setdefault(best_sym, {
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0.0,
                    "sequence": best_data["sequence"],
                    "payout_rates": {}
                })
                market_state["sequence"] = best_data["sequence"]
                save_state_unlocked()

            print(f"\n🔍 [HYBRID E/O × CALL/PUT SCANNER] Scanned {len(scanner_results)} basket markets:")
            for s, d in sorted_mkts[:3]:
                print(f"   • {s:<8}: Score={d['score']:.3f} -> Hybrid Pair: {d['sequence']} [{d['order_desc']}]")
            print(f"🎯 [BEST MARKET SELECTED] #{best_sym} with Hybrid Sequence: {market_state['sequence']}")

            stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))
            contract_type = market_state["sequence"][0]
            send_proposal(ws, contract_type, stake)

    elif msg_type == "proposal":
        proposal = data.get("proposal", {})
        active_proposal_id = proposal.get("id")
        current_market = STATE.get("current_market")
        stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))
        
        payout = proposal.get("payout", 0.0)
        with state_lock:
            market_state = STATE["markets_state"].setdefault(current_market, {
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "sequence": generate_paired_sequence(),
                "payout_rates": {}
            })
            market_state.setdefault("payout_rates", {})[str(stake)] = payout
            save_state_unlocked()
            
        send_buy(ws, active_proposal_id, stake)

    elif msg_type == "buy":
        buy = data.get("buy", {})
        active_contract_id = buy.get("contract_id")
        print(f"   • Contract Purchased: ID {active_contract_id}. Subscribing to contract results...")
        ws.send(json.dumps({"proposal_open_contract": 1, "contract_id": active_contract_id, "subscribe": 1}))

    elif msg_type == "proposal_open_contract":
        contract = data.get("proposal_open_contract", {})
        if contract.get("is_sold"):
            profit = float(contract.get("profit", 0.0))
            status = contract.get("status")  # 'won' or 'lost'
            current_market = STATE.get("current_market")
            contract_type = contract.get("contract_type", "UNKNOWN")

            with state_lock:
                market_state = STATE["markets_state"].setdefault(current_market, {
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0.0,
                    "sequence": generate_paired_sequence(),
                    "payout_rates": {}
                })
                current_sequence = market_state.get("sequence", [])
                if not is_valid_hybrid_sequence(current_sequence):
                    current_sequence = generate_paired_sequence()
                    market_state["sequence"] = current_sequence
                
                # Record trade timestamp
                now_ts = time.time()
                ts_list = STATE.setdefault("trade_timestamps", [])
                ts_list.append(now_ts)
                STATE["trade_timestamps"] = [t for t in ts_list if now_ts - t <= 3600]

                # Update running session profit & drawdown
                STATE["total_profit"] = round(STATE["total_profit"] + profit, 2)
                market_state["total_profit"] = round(market_state["total_profit"] + profit, 2)
                if STATE["total_profit"] < STATE.get("max_drawdown", 0.0):
                    STATE["max_drawdown"] = round(STATE["total_profit"], 2)

                print(f"   📊 [Trade {cycle_step}/2] Settled ({contract_type}): {status.upper()} (Profit/Loss: {'+' if profit >= 0 else ''}${profit:.2f})")

                if status == "won":
                    STATE["wins"] += 1
                    market_state["wins"] += 1
                    last_cycle_won = True
                    
                    # Full Martingale Win: reset stake and cycle profit
                    STATE["cycle_profit"] = 0.0
                    STATE["cycle_stake"] = CONFIG.get("initial_stake", 0.35)
                    STATE["consecutive_cycle_losses"] = 0
                    STATE["in_recovery"] = False
                    
                    advance_market_on_win()
                    
                    print("\n" + "="*60)
                    print(f"🎉 CYCLE RESULT: WIN (Hybrid Recovery Complete on {current_market} -> Reset Stake to ${CONFIG.get('initial_stake', 0.35):.2f}) [{BOT_NAME}]")
                    print(f"   • Net Trade Profit: +${profit:.2f}")
                    print(f"   • Market Unlocked: Will live scan fresh best market on next cycle")
                    print(f"   • Peak Stake Reached Overall: ${STATE.get('max_stake', CONFIG['initial_stake']):.2f} (on {STATE.get('max_stake_market', 'N/A')})")
                    print(f"   • Max Session Drawdown (Deepest Loss): ${STATE.get('max_drawdown', 0.0):.2f}")
                    print(f"   • Total Session Profit: ${STATE['total_profit']:.2f}")
                    print("="*60)
                    
                    save_state_unlocked()
                    trade_completed_event.set()
                    ws.close()
                else:
                    STATE["losses"] += 1
                    market_state["losses"] += 1
                    
                    # Deduct lost stake from cycle_profit
                    last_stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))
                    cycle_profit = round(STATE.get("cycle_profit", 0.0) - last_stake, 2)
                    STATE["cycle_profit"] = cycle_profit
                    
                    if STATE["cycle_profit"] < STATE.get("max_cycle_loss", 0.0):
                        STATE["max_cycle_loss"] = round(STATE["cycle_profit"], 2)
                        
                    # 2.1 Martingale Multiplier Step-Up
                    multiplier = CONFIG.get("martingale_multiplier", 2.1)
                    next_stake = round(last_stake * multiplier, 2)
                    STATE["cycle_stake"] = next_stake
                    save_state_unlocked()
                    
                    if cycle_step >= 2:
                        # Completed 2-trade sequence of losses on current market
                        last_cycle_won = False
                        STATE["consecutive_cycle_losses"] = STATE.get("consecutive_cycle_losses", 0) + 1
                        market_state["sequence"] = generate_paired_sequence()

                        recovery_cd = CONFIG.get("loss_cooldown_seconds", 1800)
                        cd_m = recovery_cd // 60
                        switch_on_loss = CONFIG.get("switch_market_on_loss", False)

                        if switch_on_loss:
                            advance_market_on_loss()
                            print("\n" + "="*60)
                            print(f"❌ CYCLE RESULT: LOSS (Both Hybrid Trades Lost on {current_market}) [{BOT_NAME}]")
                            print(f"🔄 [MARKET-SWITCH 2.1 MARTINGALE RECOVERY] Stepping up to ${next_stake:.2f} (x{multiplier}) -> Switching to a DIFFERENT market after {cd_m}m cooldown!")
                            print(f"   • Previous Market Left: {current_market} (Will scan remaining basket on next wakeup)")
                        else:
                            STATE["in_recovery"] = True
                            print("\n" + "="*60)
                            print(f"❌ CYCLE RESULT: LOSS (Both Hybrid Trades Lost on {current_market}) [{BOT_NAME}]")
                            print(f"🔒 [MARKET LOCKED FOR 2.1 MARTINGALE RECOVERY] Stepping up to ${next_stake:.2f} (x{multiplier}) -> Staying LOCKED on {current_market} with {cd_m}m cooldown!")
                            print(f"   • Active Recovery Market: {current_market}")
                        print(f"   • Peak Stake Reached Overall: ${STATE.get('max_stake', CONFIG['initial_stake']):.2f} (on {STATE.get('max_stake_market', 'N/A')})")
                        print(f"   • Max Session Drawdown: ${STATE.get('max_drawdown', 0.0):.2f}")
                        print(f"   • Deepest Cycle Deficit: ${STATE.get('max_cycle_loss', 0.0):.2f}")
                        print(f"   • Total Session Profit: ${STATE['total_profit']:.2f}")
                        print("="*60)
                        save_state_unlocked()
                        trade_completed_event.set()
                        ws.close()
                    else:
                        # Trade 1 lost -> Initiate Trade 2/2 immediately with cross-family at 2.1 Martingale step-up stake
                        cycle_step += 1
                        active_proposal_id = None
                        active_contract_id = None
                        
                        next_type = current_sequence[cycle_step - 1]
                        next_desc = get_side_description(next_type)
                        print(f"\n⚠️ Trade {cycle_step - 1} lost. 2.1 Martingale step-up to ${next_stake:.2f}. Initiating cross-family Trade {cycle_step}/2 immediately on {current_market} ({next_type} • {next_desc})...")
                        send_proposal(ws, next_type, next_stake)

def on_error(ws, error):
    print(f"[WS ERROR] {error}")
    trade_completed_event.set()

def on_close(ws, c, m):
    pass

def on_open(ws):
    global scanner_results, scanner_targets
    scanner_results = {}
    
    with state_lock:
        is_locked = STATE.get("in_recovery", False) and STATE.get("current_market") is not None
        current_market = STATE.get("current_market")
        stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))
    
    if is_locked:
        # Bot is in recovery on its locked market -> scan recent ticks on current_market to form fresh hybrid pair
        print(f"🔒 [LOCKED HYBRID RECOVERY] Bot is locked on {current_market} @ ${stake:.2f}. Scanning recent ticks to select best hybrid sequence...")
        scanner_targets = [current_market]
        ws.send(json.dumps({"ticks_history": current_market, "end": "latest", "count": 50, "style": "ticks"}))
    else:
        # Fresh trade cycle -> Run Live Market Trend Scanner across all basket markets
        basket = list(STATE.get("market_basket", []))
        if not basket:
            basket = refill_market_basket()
        scanner_targets = list(basket)
        if len(scanner_targets) == 1:
            print(f"🎯 [FOCUSED MARKET] Single market active: {scanner_targets[0]}. Scanning recent ticks...")
        else:
            print(f"🔍 [HYBRID SCANNER] Scanning last 50 ticks across {len(scanner_targets)} markets to find #1 best hybrid pair...")
        for sym in scanner_targets:
            ws.send(json.dumps({"ticks_history": sym, "end": "latest", "count": 50, "style": "ticks"}))

def acquire_lock():
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
    except Exception:
        pass
    last_wait_log = 0.0
    while True:
        try:
            os.mkdir(LOCK_PATH)
            with open(INFO_FILE, "w", encoding="utf-8") as f:
                json.dump({"owner": BOT_NAME, "timestamp": time.time()}, f)
            print(f"🔒 [LOCK] Acquired global master trade lock ({BOT_NAME}).")
            return True
        except FileExistsError:
            try:
                owner = "Another bot"
                timestamp = 0.0
                if os.path.exists(INFO_FILE):
                    try:
                        with open(INFO_FILE, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        owner = data.get("owner", "Another bot")
                        timestamp = data.get("timestamp", 0.0)
                    except Exception:
                        pass
                if timestamp > 0 and (time.time() - timestamp > 120.0):
                    print(f"⚠️ [LOCK] Stale lock detected (Owned by {owner} for {int(time.time() - timestamp)}s). Overriding.")
                    try:
                        os.rmdir(LOCK_PATH)
                    except Exception:
                        pass
                    continue
                else:
                    now = time.time()
                    if now - last_wait_log > 8.0:
                        print(f"⏳ [QUEUE DELAY] Active trade in progress by {owner}. {BOT_NAME} pausing and waiting in line...")
                        last_wait_log = now
            except Exception:
                pass
            time.sleep(random.uniform(2.0, 4.0))

def release_lock():
    try:
        if os.path.exists(INFO_FILE):
            try:
                os.remove(INFO_FILE)
            except Exception:
                pass
        if os.path.exists(LOCK_PATH):
            os.rmdir(LOCK_PATH)
            print(f"🔓 [LOCK] Released global master trade lock ({BOT_NAME}).")
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Failed to release lock: {e}")

def run_trade_cycle():
    global ws_connection, is_trade_active, cycle_step, active_proposal_id, active_contract_id, halted, last_cycle_won
    if halted:
        print(f"🛑 Bot {BOT_NAME} is halted. No new cycles will start.")
        return

    acquire_lock()
    try:
        with state_lock:
            cycle_step = 1
            active_proposal_id = None
            active_contract_id = None
            
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            curr_mkt = STATE.get("current_market") or "Scanning Trend on Wakeup..."
            in_def = STATE.get("cycle_profit", 0.0) < 0.0
            rec_str = "LOCKED (2.1 Martingale)" if STATE.get("in_recovery") else ("MARKET-SWITCH RECOVERY (2.1 Martingale)" if in_def else "SCANNING FRESH")
            stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))

            print("\n" + "="*60)
            print(f"⚡ STARTING CALL/PUT TRADE CYCLE ({BOT_NAME}): {now_str}")
            print(f"   • Bot Uptime: {get_uptime_string()}")
            print(f"   • Active Market Status: {curr_mkt} [{rec_str}] (Basket remaining: {len(STATE.get('market_basket', []))})")
            print(f"   • Active Martingale Stake: ${stake:.2f} (Deficit: ${STATE.get('cycle_profit', 0.0):.2f})")
            print(f"   • Peak Stake Reached Overall: ${STATE.get('max_stake', CONFIG['initial_stake']):.2f} (on {STATE.get('max_stake_market', 'N/A')})")
            print(f"   • Max Session Drawdown (Deepest Loss): ${STATE.get('max_drawdown', 0.0):.2f}")
            print(f"   • Deepest Cycle Deficit: ${STATE.get('max_cycle_loss', 0.0):.2f}")
            print(f"   • Total Session Profit: ${STATE['total_profit']:.2f}")
            print(f"   • Hourly Activity: {len(STATE.get('trade_timestamps', []))} trades in past 60m")
            print("="*60)

        trade_completed_event.clear()
        ws_url = get_otp_ws_url()
        if not ws_url:
            print("[ERROR] Could not fetch OTP WebSocket URL. Aborting cycle.")
            return

        ws_connection = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        wst = threading.Thread(target=ws_connection.run_forever)
        wst.daemon = True
        wst.start()

        trade_completed_event.wait(timeout=60)
        if not trade_completed_event.is_set():
            print("⚠️ [TIMEOUT] Trade sequence timed out after 60s. Forcing disconnect.")
            if ws_connection:
                ws_connection.close()
    finally:
        release_lock()

def reset_bot_globals():
    global STATE, cycle_step, active_proposal_id, active_contract_id, ws_connection, is_trade_active, halted, last_cycle_won, scanner_results, scanner_targets
    STATE = {
        "total_profit": 0.0,
        "wins": 0,
        "losses": 0,
        "current_market": None,
        "in_recovery": False,
        "market_basket": [],
        "market_index": 0,
        "cycle_profit": 0.0,
        "cycle_stake": 0.35,
        "consecutive_cycle_losses": 0,
        "max_stake": 0.35,
        "max_stake_market": "N/A",
        "max_drawdown": 0.0,
        "max_cycle_loss": 0.0,
        "trade_timestamps": [],
        "markets_state": {}
    }
    cycle_step = 1
    active_proposal_id = None
    active_contract_id = None
    ws_connection = None
    is_trade_active = False
    halted = False
    last_cycle_won = False
    scanner_results = {}
    scanner_targets = []

def run_multi_bot_scheduler(acc_mode):
    global BOT_NAME, START_TIME
    if acc_mode == "acc3":
        os.environ.setdefault("SWITCH_MARKET_ON_LOSS", "false")
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    start_ts = time.time()
    START_TIME = start_ts
    my_pid = os.getpid()

    teams = [
        ("even-odd-bot",          "even_odd_millipede_bot", 15),
        ("even-odd-fleet2-bot",   "even_odd_fleet2_bot",    60),
        ("over-under-fleet-bot",  "over_under_fleet_bot",   105),
        ("over-under-fleet2-bot", "over_under_fleet2_bot",  150),
        ("over-under-fleet3-bot", "over_under_fleet3_bot",  195),
        ("even-odd-fleet3-bot",   "even_odd_fleet3_bot",    240),
    ]

    bots_schedule = []
    for t_prefix, d_prefix, base_offset in teams:
        for i in range(1, 7):
            b_name = f"acc3-{t_prefix}-{i}"
            b_dir = f"/root/acc3_{d_prefix}_{i}"
            delay = base_offset + (i - 1) * 300
            os.makedirs(b_dir, exist_ok=True)
            meta_path = os.path.join(b_dir, "bot_meta.json")
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump({"name": b_name, "pid": my_pid, "started_at": int(start_ts)}, mf)

            log_path = os.path.join(b_dir, "bot.log")
            with open(log_path, "a", encoding="utf-8", buffering=1) as lf:
                sys.stdout = lf
                sys.stderr = lf
                os.chdir(b_dir)
                BOT_NAME = b_name
                reset_bot_globals()
                load_config(verbose=False)
                load_state(verbose=False)
                sched_time = (datetime.datetime.now() + datetime.timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                print(f"🤖 Initializing Call/Put Fleet Bot: {b_name} [Ultra-Light Single-Process Engine]")
                print(f"⏳ [STAGGER LAUNCH] Initial delay of {delay // 60}m {delay % 60}s active ({b_name}). First trade scheduled for {sched_time}.")
                print(f"🚀 [STARTING FLEET LOOP] {b_name} is active!")

            bots_schedule.append({
                "name": b_name,
                "dir": b_dir,
                "next_run": start_ts + delay
            })

    sys.stdout = orig_stdout
    sys.stderr = orig_stderr
    print(f"✅ [{acc_mode.upper()} MULTI-SCHEDULER] Managing {len(bots_schedule)} Call/Put bots in 1 process (PID {my_pid})!")

    while True:
        now = time.time()
        ready = [b for b in bots_schedule if now >= b["next_run"]]
        if not ready:
            time.sleep(1.0)
            continue

        ready.sort(key=lambda x: x["next_run"])
        bot = ready[0]
        b_name = bot["name"]
        b_dir = bot["dir"]
        log_path = os.path.join(b_dir, "bot.log")

        try:
            with open(log_path, "a", encoding="utf-8", buffering=1) as lf:
                sys.stdout = lf
                sys.stderr = lf
                os.chdir(b_dir)
                BOT_NAME = b_name
                reset_bot_globals()
                load_config(verbose=False)
                load_state(verbose=False)

                trades_before = STATE.get("wins", 0) + STATE.get("losses", 0)
                run_trade_cycle()
                trades_after = STATE.get("wins", 0) + STATE.get("losses", 0)

                if trades_after == trades_before:
                    print(f"⚠️ [RETRY SCHEDULED] No trade completed due to temporary API/network hiccup. Retrying in 20s...")
                    bot["next_run"] = time.time() + 20
                else:
                    in_deficit = STATE.get("cycle_profit", 0.0) < 0.0 or STATE.get("in_recovery", False)
                    last_won = last_cycle_won
                    if not last_won or in_deficit:
                        cooldown = CONFIG.get("loss_cooldown_seconds", 1800)
                        cd_m = cooldown // 60
                        next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
                        if CONFIG.get("switch_market_on_loss", False):
                            print(f"⏱️ [{cd_m}m RECOVERY COOLDOWN] Switching to a DIFFERENT market after {cd_m}m cooldown before next Martingale recovery @ ${STATE.get('cycle_stake', 0.35):.2f}. Next trade at {next_t}.")
                        else:
                            print(f"⏱️ [{cd_m}m RECOVERY COOLDOWN] Staying LOCKED on {STATE.get('current_market')} with {cd_m}m cooldown before next Martingale recovery @ ${STATE.get('cycle_stake', 0.35):.2f}. Next trade at {next_t}.")
                    else:
                        cooldown = CONFIG.get("win_cooldown_minutes", 30) * 60
                        cd_m = cooldown // 60
                        next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
                        print(f"✅ [{cd_m}m WIN COOLDOWN] Win achieved! Clean session profit ${STATE.get('total_profit', 0.0):.2f}. Cooldown of {cd_m}m active. Next trade scheduled at {next_t}.")
                    bot["next_run"] = time.time() + cooldown
        except Exception as e:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            print(f"[SCHEDULER ERROR] {b_name}: {e}")
            bot["next_run"] = time.time() + 30
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--multi-scheduler":
        run_multi_bot_scheduler(sys.argv[2])
        return

    print(f"🤖 Initializing Call/Put Fleet Bot (6 Bots • 30m Rest • 2.1 Martingale): {BOT_NAME}")
    load_config(verbose=True)
    load_state(verbose=True)

    # Initial stagger delay
    init_delay = int(os.getenv("INITIAL_DELAY_SECONDS", "0"))
    if init_delay > 0:
        sched_time = (datetime.datetime.now() + datetime.timedelta(seconds=init_delay)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"⏳ [STAGGER LAUNCH] Initial delay of {init_delay // 60}m {init_delay % 60}s active ({BOT_NAME}). First trade scheduled for {sched_time}.")
        time.sleep(init_delay)

    print(f"🚀 [STARTING FLEET LOOP] {BOT_NAME} is active!")
    while not halted:
        trades_before = STATE.get("wins", 0) + STATE.get("losses", 0)
        run_trade_cycle()
        trades_after = STATE.get("wins", 0) + STATE.get("losses", 0)
        if trades_after == trades_before:
            print(f"⚠️ [RETRY SCHEDULED] No trade completed due to temporary API/network hiccup. Retrying in 20s...")
            time.sleep(20)
            continue
        
        with state_lock:
            in_deficit = STATE.get("cycle_profit", 0.0) < 0.0 or STATE.get("in_recovery", False)
            last_won = last_cycle_won
            
        if not last_won or in_deficit:
            cooldown = CONFIG.get("loss_cooldown_seconds", 1800)
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            if CONFIG.get("switch_market_on_loss", False):
                print(f"⏱️ [{cd_m}m RECOVERY COOLDOWN] Switching to a DIFFERENT market after {cd_m}m cooldown before next Martingale recovery @ ${STATE.get('cycle_stake', 0.35):.2f}. Next trade at {next_t}.")
            else:
                print(f"⏱️ [{cd_m}m RECOVERY COOLDOWN] Staying LOCKED on {STATE.get('current_market')} with {cd_m}m cooldown before next Martingale recovery @ ${STATE.get('cycle_stake', 0.35):.2f}. Next trade at {next_t}.")
        else:
            cooldown = CONFIG.get("win_cooldown_minutes", 30) * 60
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"✅ [{cd_m}m WIN COOLDOWN] Win achieved! Clean session profit ${STATE.get('total_profit', 0.0):.2f}. Cooldown of {cd_m}m active. Next trade scheduled at {next_t}.")
            
        time.sleep(cooldown)

if __name__ == "__main__":
    main()
