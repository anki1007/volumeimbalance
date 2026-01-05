import requests
import time
from datetime import datetime
import pytz

from symbol_loader import load_symbols
from telegram_alert import send_alert
from config import (
    MARKET_OPEN, MARKET_CLOSE,
    VOLUME_ALERT_1, VOLUME_ALERT_2, TURNOVER_ALERT
)

IST = pytz.timezone("Asia/Kolkata")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com"
}

session = requests.Session()
session.headers.update(HEADERS)

alert_4 = set()
alert_6 = set()

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
            vol = float(q["securityWiseDP"]["tradedVolume"])

            vol_cr = vol / 1e7
            turnover = (vol * ltp) / 1e7
            pct = ((ltp - prev) / prev) * 100

            results.append({
                "symbol": sym,
                "sector": sector,
                "prev": round(prev, 2),
                "ltp": round(ltp, 2),
                "volume": round(vol_cr, 2),
                "turnover": round(turnover, 2),
                "pct": round(pct, 2)
            })

            if turnover >= TURNOVER_ALERT:
                if vol_cr >= VOLUME_ALERT_2 and sym not in alert_6:
                    send_alert(f"🔥 6Cr BLAST {sym} | {sector}")
                    alert_6.add(sym)
                elif vol_cr >= VOLUME_ALERT_1 and sym not in alert_4:
                    send_alert(f"🚨 4Cr IMBALANCE {sym} | {sector}")
                    alert_4.add(sym)

        except Exception:
            continue

    return results
