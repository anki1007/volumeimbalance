import requests, time
from datetime import datetime
import pytz

from symbol_loader import load_symbols
from telegram_alert import send_alert
from config import *

IST = pytz.timezone("Asia/Kolkata")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com"
}

session = requests.Session()
session.headers.update(HEADERS)

# alert memory (prevents repeat alerts)
vol_4 = set()
vol_6 = set()
to_1m = set()
to_d_100 = set()
to_d_500 = set()
to_d_1000 = set()

def market_open():
    now = datetime.now(IST).time()
    start = datetime.strptime(MARKET_OPEN, "%H:%M").time()
    end = datetime.strptime(MARKET_CLOSE, "%H:%M").time()
    return start <= now <= end

def get_quote(symbol):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except:
        return None

def scan():
    if not market_open():
        return []

    results = []

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
            pct = ((ltp - prev) / prev) * 100

            results.append({
                "symbol": sym,
                "sector": sector,
                "prev": round(prev,2),
                "ltp": round(ltp,2),
                "volume": round(vol_cr,2),
                "turnover": round(turnover,2),
                "pct": round(pct,2)
            })

            # 🔥 VOLUME ALERTS
            if vol_cr >= VOLUME_ALERT_2 and sym not in vol_6:
                send_alert(f"🔥 6Cr VOL BLAST\n{sym} | {sector}")
                vol_6.add(sym)

            elif vol_cr >= VOLUME_ALERT_1 and sym not in vol_4:
                send_alert(f"🚨 4Cr VOL IMBALANCE\n{sym} | {sector}")
                vol_4.add(sym)

            # ⚡ 1-MIN TURNOVER
            if turnover >= TURNOVER_1MIN and sym not in to_1m:
                send_alert(f"⚡ 100Cr TURNOVER (1min)\n{sym}")
                to_1m.add(sym)

            # 🧱 DAY TURNOVER
            if turnover >= TURNOVER_DAY_3 and sym not in to_d_1000:
                send_alert(f"🏆 1000Cr DAY TURNOVER\n{sym}")
                to_d_1000.add(sym)

            elif turnover >= TURNOVER_DAY_2 and sym not in to_d_500:
                send_alert(f"🥇 500Cr DAY TURNOVER\n{sym}")
                to_d_500.add(sym)

            elif turnover >= TURNOVER_DAY_1 and sym not in to_d_100:
                send_alert(f"🥈 100Cr DAY TURNOVER\n{sym}")
                to_d_100.add(sym)

        except:
            continue

    return results
