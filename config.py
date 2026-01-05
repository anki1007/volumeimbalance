# config.py

# GitHub RAW CSV (PRIMARY source)
GITHUB_SYMBOLS_RAW_URL = (
    "https://raw.githubusercontent.com/anki1007/volumeimbalance/main/data/symbols.csv"
)

# Telegram
TELEGRAM_BOT_TOKEN = "8302178990:AAEy6p_wBRWsM5mIcbHFcSRvmVykf0s7bso"
TELEGRAM_CHAT_ID = "8302178990"

# Thresholds (₹)
TURNOVER_4CR = 4_00_00_000
TURNOVER_6CR = 6_00_00_000

# Scanner settings
MAX_SYMBOLS = 120          # keep safe for PythonAnywhere
REQUEST_TIMEOUT = 5
MAX_RETRIES = 3
BACKOFF_SECONDS = 2
