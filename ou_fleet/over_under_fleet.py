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

LOCK_DIR = "/app/lock"
LOCK_PATH = os.path.join(LOCK_DIR, "trade_lock")
INFO_FILE = os.path.join(LOCK_DIR, "lock_info.json")
BOT_NAME = os.getenv("BOT_NAME", "my-over-under-fleet-bot-1")

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

def generate_paired_sequence(dominant_side=None):
    if dominant_side:
        opp = "DIGITOVER" if dominant_side == "DIGITUNDER" else "DIGITUNDER"
        return [dominant_side, opp]
    pair = ["DIGITUNDER", "DIGITOVER"]
    random.shuffle(pair)
    return pair

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
            if verbose:
                print(f"[SYSTEM] Loaded config: {json.dumps(CONFIG, indent=2)}")
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
    print(f"🧺 [BASKET REFILL] Basket refilled with {len(all_markets)} Over/Under markets: {STATE['market_basket']}")
    return STATE["market_basket"]

def advance_market_on_win():
    curr = STATE.get("current_market")
    basket = STATE.get("market_basket", [])
    if curr in basket:
        basket.remove(curr)
    if not basket:
        print(f"🎉 [BASKET COMPLETED] All Over/Under markets in basket completed! Refilling fresh basket!")
        refill_market_basket()
    else:
        print(f"🎉 [BASKET ADVANCE] Profit made on {curr}! Remaining in basket ({len(basket)}): {basket}")
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
        else:
            print(f"[OTP ERROR] Status: {res.status_code}, Response: {res.text}")
            return None
    except Exception as e:
        print(f"[OTP EXCEPTION] {e}")
        return None

def send_proposal(ws, contract_type, stake):
    current_market = STATE.get("current_market")
    # 50/50 Over/Under barrier: Under 5 has barrier "5", Over 4 has barrier "4"
    barrier = "4" if contract_type == "DIGITOVER" else "5"
    
    req = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": "USD",
        "duration": CONFIG.get("trade_duration", 1),
        "duration_unit": CONFIG.get("duration_unit", "t"),
        "underlying_symbol": current_market,
        "barrier": barrier
    }
    with state_lock:
        if stake > STATE.get("max_stake", 0.0) or not STATE.get("max_stake_market"):
            STATE["max_stake"] = stake
            STATE["max_stake_market"] = current_market
        save_state_unlocked()

    side_desc = "Under 5 (digits 0-4)" if contract_type == "DIGITUNDER" else "Over 4 (digits 5-9)"
    print(f"   • [Trade {cycle_step}/2] Requesting 50/50 {contract_type} ({side_desc}) on {current_market} @ ${stake:.2f}...")
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
        print(f"[API ERROR] Code: {err.get('code')}, Msg: {err.get('message')}")
        trade_completed_event.set()
        ws.close()
        return

    # Handle live scanner tick history responses for 50/50 Over/Under
    if "history" in data:
        sym = data.get("echo_req", {}).get("ticks_history")
        prices = data["history"].get("prices", [])
        pip_size = int(data.get("pip_size", 3))
        unders = 0  # 0, 1, 2, 3, 4
        overs = 0   # 5, 6, 7, 8, 9
        for p in prices:
            s = f"{p:.{pip_size}f}"
            last_digit = int(s[-1])
            if last_digit < 5:
                unders += 1
            else:
                overs += 1
        total = len(prices) if prices else 1
        bias = abs(unders - overs) / total
        dominant = "DIGITUNDER" if unders >= overs else "DIGITOVER"
        dominant_pct = (max(unders, overs) / total) * 100
        scanner_results[sym] = {
            "bias": bias,
            "dominant": dominant,
            "pct": dominant_pct,
            "unders": unders,
            "overs": overs
        }
        
        # When all targets are scanned, pick #1 best market and proceed to trade
        if len(scanner_results) >= len(scanner_targets):
            sorted_mkts = sorted(scanner_results.items(), key=lambda x: x[1]['bias'], reverse=True)
            best_sym, best_data = sorted_mkts[0]
            
            with state_lock:
                STATE["current_market"] = best_sym
                market_state = STATE["markets_state"].setdefault(best_sym, {
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0.0,
                    "sequence": generate_paired_sequence(best_data["dominant"]),
                    "payout_rates": {}
                })
                market_state["sequence"] = generate_paired_sequence(best_data["dominant"])
                save_state_unlocked()

            print(f"\n🔍 [50/50 O/U SCANNER RESULTS] Scanned {len(scanner_results)} basket markets:")
            for s, d in sorted_mkts[:3]:
                dom_label = "Under 5" if d['dominant'] == "DIGITUNDER" else "Over 4"
                print(f"   • {s:<8}: Bias Score={d['bias']:.3f} -> Dominant: {dom_label} ({d['pct']:.1f}%)")
            print(f"🎯 [BEST MARKET SELECTED] #{best_sym} with {best_data['dominant']} bias ({best_data['pct']:.1f}%). Sequence: {market_state['sequence']}")

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
                    print(f"🎉 CYCLE RESULT: WIN (Martingale Recovery Complete on {current_market} -> Reset Stake to ${CONFIG.get('initial_stake', 0.35):.2f}) [{BOT_NAME}]")
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
                        # Completed 2-trade sequence of losses on current market -> Lock for recovery
                        last_cycle_won = False
                        STATE["in_recovery"] = True
                        STATE["consecutive_cycle_losses"] = STATE.get("consecutive_cycle_losses", 0) + 1
                        market_state["sequence"] = generate_paired_sequence()

                        recovery_cd = CONFIG.get("loss_cooldown_seconds", 1200)
                        cd_m = recovery_cd // 60
                        print("\n" + "="*60)
                        print(f"❌ CYCLE RESULT: LOSS (Both 50/50 O/U Trades Lost on {current_market}) [{BOT_NAME}]")
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
                        # Trade 1 lost -> Initiate Trade 2/2 immediately on opposite side with 2.1 Martingale step-up stake
                        cycle_step += 1
                        active_proposal_id = None
                        active_contract_id = None
                        
                        next_type = current_sequence[cycle_step - 1]
                        print(f"\n⚠️ Trade {cycle_step - 1} lost. 2.1 Martingale step-up to ${next_stake:.2f}. Initiating Trade {cycle_step}/2 immediately on {current_market} ({next_type})...")
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
        # Bot is in recovery on its locked market -> place recovery trade directly
        print(f"🔒 [LOCKED MARTINGALE RECOVERY] Bot is locked on {current_market} @ ${stake:.2f}. Bypassing scanner.")
        market_state = STATE["markets_state"].setdefault(current_market, {
            "wins": 0,
            "losses": 0,
            "total_profit": 0.0,
            "sequence": generate_paired_sequence(),
            "payout_rates": {}
        })
        current_sequence = market_state.get("sequence", [])
        if not current_sequence or len(current_sequence) < 2:
            current_sequence = generate_paired_sequence()
            market_state["sequence"] = current_sequence
        contract_type = current_sequence[0]
        send_proposal(ws, contract_type, stake)
    else:
        # Fresh trade cycle -> Run Live Market Scanner across all basket markets
        basket = list(STATE.get("market_basket", []))
        if not basket:
            basket = refill_market_basket()
        scanner_targets = list(basket)
        if len(scanner_targets) == 1:
            print(f"🎯 [FOCUSED MARKET] Single market active: {scanner_targets[0]}. Scanning recent ticks...")
        else:
            print(f"🔍 [50/50 O/U SCANNER] Scanning last 50 ticks across {len(scanner_targets)} Over/Under basket markets to find #1 best market...")
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
            curr_mkt = STATE.get("current_market") or "Scanning on Wakeup..."
            rec_str = "LOCKED (2.1 Martingale)" if STATE.get("in_recovery") else "SCANNING FRESH"
            stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 0.35))

            print("\n" + "="*60)
            print(f"⚡ STARTING 50/50 OVER/UNDER TRADE CYCLE ({BOT_NAME}): {now_str}")
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

def main():
    print(f"🤖 Initializing 50/50 Over/Under Fleet Bot (2.1 Martingale Recovery): {BOT_NAME}")
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
        run_trade_cycle()
        
        with state_lock:
            in_deficit = STATE.get("cycle_profit", 0.0) < 0.0 or STATE.get("in_recovery", False)
            last_won = last_cycle_won
            
        if not last_won or in_deficit:
            cooldown = CONFIG.get("loss_cooldown_seconds", 1200)
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"⏱️ [20m RECOVERY COOLDOWN] Staying LOCKED on {STATE.get('current_market')} with {cd_m}m cooldown before next Martingale recovery @ ${STATE.get('cycle_stake', 0.35):.2f}. Next trade at {next_t}.")
        else:
            cooldown = CONFIG.get("win_cooldown_minutes", 20) * 60
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"✅ [20m WIN COOLDOWN] Win achieved! Clean session profit ${STATE.get('total_profit', 0.0):.2f}. Cooldown of {cd_m}m active. Next trade scheduled at {next_t}.")
            
        time.sleep(cooldown)

if __name__ == "__main__":
    main()
