import json
import time
import os
import sys
import hmac
import hashlib
import datetime
import threading
import random
import math
import requests

# Reconfigure standard streams for UTF-8 stability
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

LOCK_DIR = "/app/lock"
LOCK_PATH = os.path.join(LOCK_DIR, "bybit_trade_lock")
INFO_FILE = os.path.join(LOCK_DIR, "bybit_lock_info.json")
BOT_NAME = os.getenv("BOT_NAME", "my-bybit-fleet-bot-1")

UPTIME_OFFSET_SECONDS = int(os.getenv("UPTIME_OFFSET_SECONDS", "0"))
START_TIME = time.time()

CONFIG = {}
STATE = {
    "total_profit": 0.0,
    "daily_profit": 0.0,
    "daily_date": "",
    "wins": 0,
    "losses": 0,
    "current_market": None,
    "in_recovery": False,
    "market_basket": [],
    "cycle_profit": 0.0,
    "cycle_stake": 2.0,
    "consecutive_cycle_losses": 0,
    "max_stake": 2.0,
    "max_stake_market": "N/A",
    "max_drawdown": 0.0,
    "max_cycle_loss": 0.0,
    "trade_timestamps": [],
    "markets_state": {}
}
state_lock = threading.RLock()
halted = False
last_cycle_won = False
instrument_cache = {}


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
        opp = "SHORT" if dominant_side == "LONG" else "LONG"
        return [dominant_side, opp]
    pair = ["LONG", "SHORT"]
    random.shuffle(pair)
    return pair


def get_base_url():
    mode = CONFIG.get("mode", "demo").lower()
    if mode == "live" or mode == "mainnet":
        return "https://api.bybit.com"
    elif mode == "testnet":
        return "https://api-testnet.bybit.com"
    return "https://api-demo.bybit.com"


def bybit_request(method, endpoint, params=None, auth=False):
    base_url = get_base_url()
    url = f"{base_url}{endpoint}"
    headers = {"Content-Type": "application/json"}
    params = params or {}

    if auth:
        api_key = CONFIG.get("api_key", "")
        api_secret = CONFIG.get("api_secret", "")
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"

        if method.upper() == "GET":
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            payload = timestamp + api_key + recv_window + query_string
            if query_string:
                url = f"{url}?{query_string}"
            body_str = None
        else:
            body_str = json.dumps(params)
            payload = timestamp + api_key + recv_window + body_str

        signature = hmac.new(
            api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers.update({
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window
        })

        try:
            if method.upper() == "GET":
                res = requests.get(url, headers=headers, timeout=12)
            else:
                res = requests.post(url, headers=headers, data=body_str, timeout=12)
            return res.json()
        except Exception as e:
            print(f"[BYBIT API EXCEPTION] {endpoint}: {e}")
            return {"retCode": -1, "retMsg": str(e)}
    else:
        try:
            res = requests.get(url, params=params, headers=headers, timeout=12)
            return res.json()
        except Exception as e:
            print(f"[BYBIT PUBLIC API EXCEPTION] {endpoint}: {e}")
            return {"retCode": -1, "retMsg": str(e)}


def load_config(verbose=False):
    global CONFIG
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                CONFIG = json.load(f)
            if os.getenv("BYBIT_API_KEY"):
                CONFIG["api_key"] = os.getenv("BYBIT_API_KEY")
            if os.getenv("BYBIT_API_SECRET"):
                CONFIG["api_secret"] = os.getenv("BYBIT_API_SECRET")
            if verbose:
                safe_cfg = dict(CONFIG)
                if "api_secret" in safe_cfg and len(safe_cfg["api_secret"]) > 6:
                    safe_cfg["api_secret"] = safe_cfg["api_secret"][:4] + "****"
                print(f"[SYSTEM] Loaded config: {json.dumps(safe_cfg, indent=2)}")
        else:
            print(f"[ERROR] Config file {CONFIG_FILE} not found!")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}")
        sys.exit(1)


def refill_market_basket():
    all_markets = list(CONFIG.get("markets", []))
    random.shuffle(all_markets)
    STATE["market_basket"] = all_markets
    print(f"🧺 [BASKET REFILL] Basket refilled with {len(all_markets)} Bybit Futures markets: {STATE['market_basket']}")
    return STATE["market_basket"]


def advance_market_on_win():
    curr = STATE.get("current_market")
    basket = STATE.get("market_basket", [])
    if curr in basket:
        basket.remove(curr)
    if not basket:
        print("🎉 [BASKET COMPLETED] All Bybit markets in basket completed! Refilling fresh basket!")
        refill_market_basket()
    else:
        print(f"🎉 [BASKET ADVANCE] Profit made on {curr}! Remaining in basket ({len(basket)}): {basket}")
    STATE["current_market"] = None
    STATE["in_recovery"] = False
    return STATE.get("market_basket", [None])[0]


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
                    "sequence": generate_paired_sequence()
                }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to save state: {e}")


def load_state(verbose=False):
    global STATE
    with state_lock:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    STATE.update(loaded)
                if STATE.get("daily_date") != today_str:
                    STATE["daily_date"] = today_str
                    STATE["daily_profit"] = 0.0
                if verbose:
                    print(f"[SYSTEM] Loaded state: {json.dumps(STATE, indent=2)}")
            else:
                STATE["daily_date"] = today_str
                STATE["daily_profit"] = 0.0
                STATE["cycle_stake"] = CONFIG.get("initial_stake", 2.0)
                STATE["max_stake"] = CONFIG.get("initial_stake", 2.0)
                if verbose:
                    print("[SYSTEM] No state file found. Initializing new state.")
                if not STATE.get("market_basket"):
                    refill_market_basket()
                save_state_unlocked()
        except Exception as e:
            print(f"[ERROR] Failed to load state: {e}")


def get_instrument_rules(symbol):
    if symbol in instrument_cache:
        return instrument_cache[symbol]
    res = bybit_request("GET", "/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
    if res.get("retCode") == 0:
        items = res.get("result", {}).get("list", [])
        if items:
            lot_filter = items[0].get("lotSizeFilter", {})
            price_filter = items[0].get("priceFilter", {})
            rules = {
                "min_qty": float(lot_filter.get("minOrderQty", 1)),
                "qty_step": str(lot_filter.get("qtyStep", "1")),
                "min_notional": float(lot_filter.get("minNotionalValue", 5.0)),
                "tick_size": str(price_filter.get("tickSize", "0.0001"))
            }
            instrument_cache[symbol] = rules
            return rules
    return {"min_qty": 1.0, "qty_step": "1", "min_notional": 5.0, "tick_size": "0.0001"}


def format_by_step(value, step_str, round_up=False):
    from decimal import Decimal, ROUND_DOWN, ROUND_UP
    d_val = Decimal(str(value))
    d_step = Decimal(str(step_str))
    if d_step <= 0:
        return str(value)
    rounding = ROUND_UP if round_up else ROUND_DOWN
    steps = (d_val / d_step).to_integral_value(rounding=rounding)
    result = steps * d_step
    return format(result.normalize(), "f") if result == result.to_integral() and "." not in str(step_str) else format(result, "f")


def ensure_leverage(symbol, leverage):
    bybit_request("POST", "/v5/position/set-leverage", {
        "category": "linear",
        "symbol": symbol,
        "buyLeverage": str(leverage),
        "sellLeverage": str(leverage)
    }, auth=True)


def scan_best_bybit_market(targets):
    scanner_results = {}
    print(f"🔍 [BYBIT TREND SCANNER] Scanning recent 1m price momentum across {len(targets)} markets...")
    for sym in targets:
        res = bybit_request("GET", "/v5/market/kline", {
            "category": "linear",
            "symbol": sym,
            "interval": "1",
            "limit": 30
        })
        if res.get("retCode") == 0:
            klines = res.get("result", {}).get("list", [])
            if len(klines) >= 5:
                # Bybit returns klines newest first -> reverse to chronological order
                closes = [float(k[4]) for k in reversed(klines)]
                start_p = closes[0]
                end_p = closes[-1]
                max_p = max(closes)
                min_p = min(closes)
                rng = max_p - min_p if max_p != min_p else 1.0

                up_moves = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
                down_moves = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
                total_moves = up_moves + down_moves if (up_moves + down_moves) > 0 else 1

                is_up = end_p >= start_p
                dominant = "LONG" if is_up else "SHORT"
                momentum_score = (up_moves / total_moves) if is_up else (down_moves / total_moves)
                bias = abs(end_p - start_p) / rng + momentum_score

                scanner_results[sym] = {
                    "bias": bias,
                    "dominant": dominant,
                    "last_price": end_p,
                    "pct": momentum_score * 100
                }

    if not scanner_results:
        fallback = targets[0]
        return fallback, {"bias": 1.0, "dominant": "LONG", "last_price": 0.0, "pct": 50.0}

    sorted_mkts = sorted(scanner_results.items(), key=lambda x: x[1]["bias"], reverse=True)
    print(f"\n🔍 [BYBIT TREND SCANNER] Scanned {len(scanner_results)} basket markets:")
    for s, d in sorted_mkts[:3]:
        print(f"   • {s:<10}: Trend Bias={d['bias']:.3f} -> Dominant: {d['dominant']} ({d['pct']:.1f}% Momentum)")
    best_sym, best_data = sorted_mkts[0]
    return best_sym, best_data


def get_latest_price(symbol):
    res = bybit_request("GET", "/v5/market/tickers", {"category": "linear", "symbol": symbol})
    if res.get("retCode") == 0:
        items = res.get("result", {}).get("list", [])
        if items:
            return float(items[0].get("lastPrice", 0.0))
    return 0.0


def execute_single_bybit_trade(symbol, direction, stake, step_num):
    """
    Places a LONG (Buy) or SHORT (Sell) market order with tight TP/SL,
    waits for resolution, and returns (won: bool, net_profit: float).
    """
    leverage = float(CONFIG.get("leverage", 5))
    tp_pct = float(CONFIG.get("tp_percent", 0.15)) / 100.0
    sl_pct = float(CONFIG.get("sl_percent", 0.15)) / 100.0
    max_wait = int(CONFIG.get("max_trade_wait_seconds", 180))

    ensure_leverage(symbol, int(leverage))
    rules = get_instrument_rules(symbol)
    entry_price = get_latest_price(symbol)
    if entry_price <= 0:
        print(f"[ERROR] Could not fetch price for {symbol}.")
        return None, 0.0

    # Calculate position notional = stake * leverage
    notional = max(stake * leverage, rules.get("min_notional", 5.0) * 1.05)
    raw_qty = notional / entry_price
    if raw_qty < rules["min_qty"]:
        raw_qty = rules["min_qty"]
    qty_str = format_by_step(raw_qty, rules["qty_step"], round_up=True)
    actual_qty = float(qty_str)

    if direction == "LONG":
        bybit_side = "Buy"
        tp_price = entry_price * (1.0 + tp_pct)
        sl_price = entry_price * (1.0 - sl_pct)
    else:
        bybit_side = "Sell"
        tp_price = entry_price * (1.0 - tp_pct)
        sl_price = entry_price * (1.0 + sl_pct)

    tp_str = format_by_step(tp_price, rules["tick_size"])
    sl_str = format_by_step(sl_price, rules["tick_size"])

    with state_lock:
        if stake > STATE.get("max_stake", 0.0) or not STATE.get("max_stake_market"):
            STATE["max_stake"] = stake
            STATE["max_stake_market"] = symbol
        save_state_unlocked()

    print(
        f"   • [Trade {step_num}/2] Placing {direction} ({bybit_side}) on {symbol} | "
        f"Margin Stake: ${stake:.2f} ({int(leverage)}x Lev, Qty: {qty_str}) | "
        f"Entry: ~{entry_price} | TP: {tp_str} | SL: {sl_str}..."
    )

    trade_start_ms = int(time.time() * 1000) - 1000
    order_res = bybit_request("POST", "/v5/order/create", {
        "category": "linear",
        "symbol": symbol,
        "side": bybit_side,
        "orderType": "Market",
        "qty": qty_str,
        "takeProfit": tp_str,
        "stopLoss": sl_str,
        "tpTriggerBy": "LastPrice",
        "slTriggerBy": "LastPrice",
        "positionIdx": 0
    }, auth=True)

    if order_res.get("retCode") != 0:
        print(f"[BYBIT ORDER ERROR] Code: {order_res.get('retCode')}, Msg: {order_res.get('retMsg')}")
        return None, 0.0

    order_id = order_res.get("result", {}).get("orderId")
    print(f"   • Order Active (ID: {order_id}). Monitoring live position for fast TP/SL hit...")

    start_wait = time.time()
    while time.time() - start_wait < max_wait:
        time.sleep(1.5)
        pos_res = bybit_request("GET", "/v5/position/list", {"category": "linear", "symbol": symbol}, auth=True)
        if pos_res.get("retCode") == 0:
            pos_list = pos_res.get("result", {}).get("list", [])
            if pos_list:
                size = float(pos_list[0].get("size", 0.0))
                if size == 0.0:
                    # Position closed via TP or SL!
                    break

    # If still open after max_wait, close at market so cycle can finish cleanly
    pos_res = bybit_request("GET", "/v5/position/list", {"category": "linear", "symbol": symbol}, auth=True)
    if pos_res.get("retCode") == 0:
        pos_list = pos_res.get("result", {}).get("list", [])
        if pos_list and float(pos_list[0].get("size", 0.0)) > 0:
            close_side = "Sell" if bybit_side == "Buy" else "Buy"
            print(f"   ⏱️ Max wait ({max_wait}s) reached. Closing {symbol} position at market...")
            bybit_request("POST", "/v5/order/create", {
                "category": "linear",
                "symbol": symbol,
                "side": close_side,
                "orderType": "Market",
                "qty": qty_str,
                "reduceOnly": True,
                "positionIdx": 0
            }, auth=True)

    # Fetch closed PnL record from Bybit (poll up to 5s for Bybit indexer)
    net_profit = 0.0
    for _ in range(5):
        time.sleep(1.0)
        pnl_res = bybit_request("GET", "/v5/position/closed-pnl", {
            "category": "linear",
            "symbol": symbol,
            "limit": 5
        }, auth=True)
        if pnl_res.get("retCode") == 0:
            records = pnl_res.get("result", {}).get("list", [])
            for rec in records:
                if int(rec.get("updatedTime", 0)) >= trade_start_ms:
                    net_profit = float(rec.get("closedPnl", 0.0))
                    break
            if net_profit != 0.0:
                break

    won = net_profit > 0.0
    return won, round(net_profit, 4)


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
            print(f"🔒 [LOCK] Acquired Bybit master trade lock ({BOT_NAME}).")
            return True
        except FileExistsError:
            try:
                owner = "Another bot"
                timestamp = 0.0
                if os.path.exists(INFO_FILE):
                    with open(INFO_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    owner = data.get("owner", "Another bot")
                    timestamp = data.get("timestamp", 0.0)
                if timestamp > 0 and (time.time() - timestamp > 400.0):
                    print(f"⚠️ [LOCK] Stale lock detected (Owned by {owner}). Overriding.")
                    try:
                        os.rmdir(LOCK_PATH)
                    except Exception:
                        pass
                    continue
                else:
                    now = time.time()
                    if now - last_wait_log > 8.0:
                        print(f"⏳ [QUEUE DELAY] Active Bybit trade in progress by {owner}. {BOT_NAME} waiting in line...")
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
            print(f"🔓 [LOCK] Released Bybit master trade lock ({BOT_NAME}).")
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Failed to release lock: {e}")


def run_trade_cycle():
    acquire_lock()
    try:
        _run_trade_cycle_inner()
    finally:
        release_lock()


def _run_trade_cycle_inner():
    global last_cycle_won, halted
    if halted:
        return

    with state_lock:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        if STATE.get("daily_date") != today_str:
            STATE["daily_date"] = today_str
            STATE["daily_profit"] = 0.0
            save_state_unlocked()

        is_locked = STATE.get("in_recovery", False) and STATE.get("current_market") is not None
        current_market = STATE.get("current_market")
        stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 2.0))

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        curr_mkt = current_market or "Scanning Trend on Wakeup..."
        rec_str = "LOCKED (Martingale Recovery)" if is_locked else "SCANNING FRESH"

        print("\n" + "=" * 65)
        print(f"⚡ STARTING BYBIT LONG/SHORT CYCLE ({BOT_NAME}): {now_str}")
        print(f"   • Bot Uptime: {get_uptime_string()}")
        print(f"   • Mode: {CONFIG.get('mode', 'demo').upper()} ({get_base_url()})")
        print(f"   • Active Market Status: {curr_mkt} [{rec_str}] (Basket remaining: {len(STATE.get('market_basket', []))})")
        print(f"   • Active Stake: ${stake:.2f} (Deficit: ${STATE.get('cycle_profit', 0.0):.2f})")
        print(f"   • Today's Profit: ${STATE.get('daily_profit', 0.0):.2f} / ${CONFIG.get('daily_tp_target', 50.0):.2f} Daily Target")
        print(f"   • Total Session Profit: ${STATE['total_profit']:.2f}")
        print("=" * 65)

    if not is_locked:
        basket = list(STATE.get("market_basket", []))
        if not basket:
            basket = refill_market_basket()
        best_sym, best_data = scan_best_bybit_market(basket)
        with state_lock:
            current_market = best_sym
            STATE["current_market"] = best_sym
            market_state = STATE["markets_state"].setdefault(best_sym, {
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "sequence": generate_paired_sequence(best_data["dominant"])
            })
            market_state["sequence"] = generate_paired_sequence(best_data["dominant"])
            sequence = list(market_state["sequence"])
            save_state_unlocked()
        print(f"🎯 [BEST MARKET SELECTED] #{best_sym} with {best_data['dominant']} trend. Sequence: {sequence}")
    else:
        with state_lock:
            market_state = STATE["markets_state"].setdefault(current_market, {
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "sequence": generate_paired_sequence()
            })
            sequence = list(market_state.get("sequence") or generate_paired_sequence())
            print(f"🔒 [LOCKED MARTINGALE RECOVERY] Bot locked on {current_market} @ ${stake:.2f}. Sequence: {sequence}")

    # Run 2-step sequence (e.g., Trade 1/2 LONG -> if loss, immediate switch to Trade 2/2 SHORT)
    for step_num in (1, 2):
        direction = sequence[step_num - 1]
        with state_lock:
            stake = STATE.get("cycle_stake", CONFIG.get("initial_stake", 2.0))

        won, profit = execute_single_bybit_trade(current_market, direction, stake, step_num)
        if won is None:
            print("⚠️ [ABORT] Trade could not be executed (check API keys or Demo balance). Waiting before retry.")
            return

        with state_lock:
            market_state = STATE["markets_state"][current_market]
            STATE["total_profit"] = round(STATE["total_profit"] + profit, 2)
            STATE["daily_profit"] = add_fleet_daily_profit(profit)
            market_state["total_profit"] = round(market_state["total_profit"] + profit, 2)
            if STATE["total_profit"] < STATE.get("max_drawdown", 0.0):
                STATE["max_drawdown"] = round(STATE["total_profit"], 2)

            status_str = "WON" if won else "LOST"
            print(f"   📊 [Trade {step_num}/2] Settled ({direction}): {status_str} (PnL: {'+' if profit >= 0 else ''}${profit:.2f})")

            if won:
                STATE["wins"] += 1
                market_state["wins"] += 1
                last_cycle_won = True

                STATE["cycle_profit"] = 0.0
                STATE["cycle_stake"] = CONFIG.get("initial_stake", 15.0)
                STATE["consecutive_cycle_losses"] = 0
                STATE["in_recovery"] = False

                advance_market_on_win()
                save_state_unlocked()

                print("\n" + "=" * 65)
                print(f"🎉 CYCLE RESULT: WIN on {current_market} -> Reset Stake to ${CONFIG.get('initial_stake', 15.0):.2f} [{BOT_NAME}]")
                print(f"   • Net Trade Profit: +${profit:.2f}")
                print(f"   • Fleet Today's Profit: ${STATE['daily_profit']:.2f} / ${CONFIG.get('daily_tp_target', 50.0):.2f}")
                print(f"   • Bot Session Profit: ${STATE['total_profit']:.2f}")
                print("=" * 65)
                return
            else:
                STATE["losses"] += 1
                market_state["losses"] += 1
                STATE["cycle_profit"] = round(STATE.get("cycle_profit", 0.0) + profit, 2)
                if STATE["cycle_profit"] < STATE.get("max_cycle_loss", 0.0):
                    STATE["max_cycle_loss"] = STATE["cycle_profit"]

                multiplier = float(CONFIG.get("martingale_multiplier", 2.1))
                next_stake = round(stake * multiplier, 2)
                STATE["cycle_stake"] = next_stake
                save_state_unlocked()

                if step_num == 1:
                    opp_dir = sequence[1]
                    print(f"\n⚠️ Trade 1/2 ({direction}) lost. Martingale step-up to ${next_stake:.2f}. Switching immediately to {opp_dir} (Trade 2/2)...")
                else:
                    last_cycle_won = False
                    STATE["in_recovery"] = True
                    STATE["consecutive_cycle_losses"] = STATE.get("consecutive_cycle_losses", 0) + 1
                    market_state["sequence"] = generate_paired_sequence()
                    save_state_unlocked()

                    cd_m = int(CONFIG.get("loss_cooldown_seconds", 1200)) // 60
                    print("\n" + "=" * 65)
                    print(f"❌ CYCLE RESULT: LOSS (Both LONG & SHORT lost on {current_market}) [{BOT_NAME}]")
                    print(f"🔒 [MARKET LOCKED FOR RECOVERY] Next Stake: ${next_stake:.2f} -> Entering {cd_m}m cooldown!")
                    print("=" * 65)


def get_fleet_daily_profit():
    daily_file = os.path.join(LOCK_DIR, "daily_fleet_profit.json")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        if os.path.exists(daily_file):
            with open(daily_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                return float(data.get("profit", 0.0))
    except Exception:
        pass
    return float(STATE.get("daily_profit", 0.0))


def add_fleet_daily_profit(delta):
    daily_file = os.path.join(LOCK_DIR, "daily_fleet_profit.json")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    current = 0.0
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        if os.path.exists(daily_file):
            with open(daily_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                current = float(data.get("profit", 0.0))
        updated = round(current + delta, 2)
        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump({"date": today_str, "profit": updated}, f)
        return updated
    except Exception:
        return round(STATE.get("daily_profit", 0.0) + delta, 2)


def check_daily_target_and_sleep():
    daily_target = float(CONFIG.get("daily_tp_target", 50.0))
    with state_lock:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        fleet_daily = get_fleet_daily_profit()
        if STATE.get("daily_date") != today_str:
            STATE["daily_date"] = today_str
        STATE["daily_profit"] = fleet_daily
        save_state_unlocked()
        in_recovery = STATE.get("in_recovery", False)

    # Only sleep on Daily Target when not mid-recovery
    if fleet_daily >= daily_target and not in_recovery:
        now = datetime.datetime.now()
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        sleep_secs = max(60, int((tomorrow - now).total_seconds()))
        hrs = sleep_secs // 3600
        mins = (sleep_secs % 3600) // 60
        print("\n" + "🏆" * 30)
        print(f"🎯 FLEET DAILY PROFIT TARGET REACHED! (${fleet_daily:.2f} / ${daily_target:.2f})")
        print(f"😴 Locking in winnings! {BOT_NAME} going to sleep for {hrs}h {mins}m until tomorrow ({tomorrow.strftime('%Y-%m-%d %H:%M:%S')}).")
        print("🏆" * 30 + "\n")
        time.sleep(sleep_secs)


def main():
    print(f"🤖 Initializing Bybit Long/Short Fleet Bot: {BOT_NAME}")
    load_config(verbose=True)
    load_state(verbose=True)

    if "PASTE_YOUR" in CONFIG.get("api_key", ""):
        print("\n⚠️ [SETUP REQUIRED] Please paste your Bybit Demo API Key and Secret into Bybit_Fleet_Bot/config.json!")
        return

    init_delay = int(os.getenv("INITIAL_DELAY_SECONDS", "0"))
    if init_delay > 0:
        sched_time = (datetime.datetime.now() + datetime.timedelta(seconds=init_delay)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"⏳ [STAGGER LAUNCH] Initial delay of {init_delay // 60}m {init_delay % 60}s active. First trade at {sched_time}.")
        time.sleep(init_delay)

    while not halted:
        check_daily_target_and_sleep()
        run_trade_cycle()
        check_daily_target_and_sleep()

        with state_lock:
            in_deficit = STATE.get("cycle_profit", 0.0) < 0.0 or STATE.get("in_recovery", False)
            last_won = last_cycle_won

        if not last_won or in_deficit:
            cooldown = int(CONFIG.get("loss_cooldown_seconds", 1200))
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"⏱️ [{cd_m}m RECOVERY COOLDOWN] Staying LOCKED on {STATE.get('current_market')} before next recovery @ ${STATE.get('cycle_stake', 2.0):.2f}. Next trade at {next_t}.")
        else:
            cooldown = int(CONFIG.get("win_cooldown_minutes", 20)) * 60
            cd_m = cooldown // 60
            next_t = (datetime.datetime.now() + datetime.timedelta(seconds=cooldown)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"✅ [{cd_m}m WIN COOLDOWN] Win achieved! Today's profit: ${STATE.get('daily_profit', 0.0):.2f}. Cooldown of {cd_m}m active. Next trade at {next_t}.")

        time.sleep(cooldown)


if __name__ == "__main__":
    main()
