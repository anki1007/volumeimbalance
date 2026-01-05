# scanner.py

import time
import requests
from datetime import datetime, time as dtime
import pytz

from symbol_loader import load_symbols
from telegram_alert import send_alert
from config import (
    TURNOVER_4CR,
    TURNOVER_6CR,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    BACKOFF_SECONDS,
)

IST = pytz.timezone("Asia/Kolkata")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

def market_open():
    now = datetime.now(IST).time()
    return dtime(9, 15) <= now <= dtime(15, 30)

def fetch_quote(symbol):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=HEADERS, timeout=5)

    for i in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except Exception:
            time.sleep(BACKOFF_SECONDS * (i + 1))
    return None

def scan():
    if not market_open():
        return []

    results = []
    symbols = load_symbols()

    for item in symbols:
        symbol = item["Symbol"]
        sector = item["Sector"]

        data = fetch_quote(symbol)
        if not data:
            continue

        try:
            price = data["priceInfo"]
            trade = data["securityWiseDP"]

            prev = price["previousClose"]
            ltp = price["lastPrice"]
            volume = trade["tradedVolume"]
            turnover = trade["tradedValue"]

            vol_cr = round(volume / 1e7, 2)
            pct = round(((ltp - prev) / prev) * 100, 2)

            row = {
                "symbol": symbol,
                "sector": sector,
                "prev": prev,
                "ltp": ltp,
                "vol_cr": vol_cr,
                "turnover": turnover,
                "pct": pct,
            }

            if turnover >= TURNOVER_6CR:
                send_alert("🚨 6 CR TURNOVER ALERT", row)
            elif turnover >= TURNOVER_4CR:
                send_alert("⚠️ 4 CR TURNOVER ALERT", row)

            if turnover >= TURNOVER_4CR:
                results.append(row)

        except Exception:
            continue

        time.sleep(0.2)

    return results
