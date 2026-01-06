import requests, time, json, os
from datetime import datetime
import pytz

from symbol_loader import load_symbols
from telegram_alert import send_alert
from config import *

IST = pytz.timezone("Asia/Kolkata")

# ─── NSE SESSION (MANDATORY) ────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
    "Accept-Language": "en-US,en;q=0.9"
})

# Bootstrap cookies (ABSOLUTELY REQUIRED)
session.get("https://www.nseindia.com", timeout=5)

# ─── ALERT STATE (PERSISTENT) ────────────────────────────────────────────────
STATE_FILE = "alert_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "vol_4": [], "vol_6": [],
        "to_1m": [],
        "to_d_100": [], "to_d_500": [], "to_d_1000": []
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ─── MARKET TIME CHECK ──────────────────────────────────────────────────────
def market_open():
    now = datetime.now(IST).time()
    start = datetime.strptime(MARKET_OPEN, "%H:%M").time()
    end = datetime.strptime(MARKET_CLOSE, "%H:%M").time()
    return start <= now <= end

# ─── NSE QUOTE ──────────────────────────────────────────────────────────────
def get_quote(symbol):
    try:
        r = session.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
            timeout=5
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"NSE error {symbol}: {e}")
        return None

# ─── MAIN SCAN ──────────────────────────────────────────────────────────────
def scan():
    if not market_open():
        print("Market closed, skipping scan")
        return

    state = load_state()

    for s in load_symbols():
        sym = s["symbol"]
        sector = s["sector"]

        q = get_quote(sym)
        if not q:
            continue

        try:
            ltp = float(q["priceInfo"]["lastPrice"])
            prev = float(q["priceInfo"]["previousClose"])
            vol = float(q["securityWiseDP"]["tradedVolume"])

            vol_cr = vol / 1e7
            turnover = (vol * ltp) / 1e7

            # 🔥 VOLUME ALERTS
            if vol_cr >= VOLUME_ALERT_2 and sym not in state["vol_6"]:
                send_alert(f"🔥 6Cr VOL BLAST\n{sym} | {sector}")
                state["vol_6"].append(sym)

            elif vol_cr >= VOLUME_ALERT_1 and sym not in state["vol_4"]:
                send_alert(f"🚨 4Cr VOL IMBALANCE\n{sym} | {sector}")
                state["vol_4"].append(sym)

            # ⚡ 1-MIN TURNOVER
            if turnover >= TURNOVER_1MIN and sym not in state["to_1m"]:
                send_alert(f"⚡ 100Cr TURNOVER (1min)\n{sym}")
                state["to_1m"].append(sym)

            # 🧱 DAY TURNOVER
            if turnover >= TURNOVER_DAY_3 and sym not in state["to_d_1000"]:
                send_alert(f"🏆 1000Cr DAY TURNOVER\n{sym}")
                state["to_d_1000"].append(sym)

            elif turnover >= TURNOVER_DAY_2 and sym not in state["to_d_500"]:
                send_alert(f"🥇 500Cr DAY TURNOVER\n{sym}")
                state["to_d_500"].append(sym)

            elif turnover >= TURNOVER_DAY_1 and sym not in state["to_d_100"]:
                send_alert(f"🥈 100Cr DAY TURNOVER\n{sym}")
                state["to_d_100"].append(sym)

            save_state(state)

            time.sleep(0.2)  # RATE LIMIT (CRITICAL)

        except Exception as e:
            print(sym, e)
            continue
