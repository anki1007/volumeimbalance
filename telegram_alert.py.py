import requests

BOT_TOKEN = "8302178990:AAEy6p_wBRWsM5mIcbHFcSRvmVykf0s7bso"
CHAT_ID = "8302178990"

def send_alert(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": msg},
        timeout=10
    )
