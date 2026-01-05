# telegram_alert.py

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_alert(title, row):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    message = f"""
{title}

Stock: {row['symbol']}
Sector: {row['sector']}
Prev Close: {row['prev']}
LTP: {row['ltp']}
Volume (Cr): {row['vol_cr']}
Turnover: ₹{row['turnover']:,}
Change: {row['pct']}%
"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass
