import requests
import time
from datetime import datetime
import pytz

from symbol_loader import load_symbols
from telegram_alert import send_alert
from config import MARKET_OPEN, MARKET_CLOSE

IST = pytz.timezone("Asia/Kolkata")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com"
}

session = requests.Session()
session.headers.update(HEADERS)

# ---- STATE ----
prev_snapshot = {}     # symbol -> {volume, turnover}
alerted = set()        # (symbol, condition)

# ---- HELPERS ----
def market_open():
    now = datetime.now(IST).time()
    start = datetime.strptime(MARKET_OPEN, "%H:%M").time()
    end = datetime.strptime(MARKET_CLOSE, "%H:%M").time()
    return start <= now <= end

def get_quote(symbol, retries=3):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    delay = 1
    for _ in range(retries):
        try:
            r = session.get(url, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(delay)
            delay *= 2
    return None

# ---- MAIN SCAN ----
def scan():
    if not market_open():
        return []

    results = []

    for item in load_symbols():
        sym = item["symbol"]
        sector = item["sector"]

        q = get_quote(sym)
        if not q:
            continue

        try:
            ltp = float(q["priceInfo"]["lastPrice"])
            prev = float(q["priceInfo"]["previousClose"])

            day_volume = float(q["securityWiseDP"]["tradedVolume"])
            day_turnover = (day_volume * ltp) / 1e7  # Cr

            # ---- PER MINUTE CALCULATION ----
            last = prev_snapshot.get(sym, {"volume": day_volume, "turnover": day_turnover})

            vol_1m = (day_volume - last["volume"]) / 1e7
            to_1m = day_turnover - last["turnover"]

            prev_snapshot[sym] = {
                "volume": day_volume,
                "turnover": day_turnover
            }

            pct = ((ltp - prev) / prev) * 100

            # ---- ALERT CONDITIONS ----

            def fire(tag, msg):
                key = (sym, tag)
                if key not in alerted:
                    send_alert(msg)
                    alerted.add(key)

            # 1️⃣ 4 Cr / min
            if vol_1m >= 4:
                fire("VOL_4_1M",
                     f"🚨 4Cr VOL / 1m\n{sym} | {sector}\nVol: {vol_1m:.2f} Cr")

            # 2️⃣ 6 Cr / min
            if vol_1m >= 6:
                fire("VOL_6_1M",
                     f"🔥 6Cr VOL / 1m\n{sym} | {sector}\nVol: {vol_1m:.2f} Cr")

            # 3️⃣ 100 Cr turnover / min
            if to_1m >= 100:
                fire("TO_100_1M",
                     f"💥 100Cr TO / 1m\n{sym} | {sector}\nTO: {to_1m:.2f} Cr")

            # 4️⃣ Day 100 Cr
            if day_turnover >= 100:
                fire("DAY_TO_100",
                     f"📊 100Cr DAY TO\n{sym} | {sector}\nTO: {day_turnover:.2f} Cr")

            # 5️⃣ Day 500 Cr
            if day_turnover >= 500:
                fire("DAY_TO_500",
                     f"🚀 500Cr DAY TO\n{sym} | {sector}\nTO: {day_turnover:.2f} Cr")

            # 6️⃣ Day 1000 Cr
            if day_turnover >= 1000:
                fire("🟣 DAY_TO_1000",
                     f"👑 1000Cr DAY TO\n{sym} | {sector}\nTO: {day_turnover:.2f} Cr")

            results.append({
                "symbol": sym,
                "sector": sector,
                "prev": round(prev, 2),
                "ltp": round(ltp, 2),
                "vol_1m": round(vol_1m, 2),
                "to_1m": round(to_1m, 2),
                "day_to": round(day_turnover, 2),
                "pct": round(pct, 2)
            })

        except Exception:
            continue

    return results
