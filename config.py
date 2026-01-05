# config.py

# GitHub RAW CSV (PRIMARY source)
GITHUB_SYMBOLS_RAW_URL = (
    "https://raw.githubusercontent.com/anki1007/volumeimbalance/main/data/symbols.csv"
)

# Telegram
TELEGRAM_BOT_TOKEN = "8570165864:AAHDhsmoFUnl9LrgvE2YsA-lXz9dUEcaEB8"
TELEGRAM_CHAT_ID = 266899337

# Thresholds (₹)
TURNOVER_4CR = 4_00_00_000
TURNOVER_6CR = 6_00_00_000

# Scanner settings
MAX_SYMBOLS = 120          # keep safe for PythonAnywhere
REQUEST_TIMEOUT = 5
MAX_RETRIES = 3
BACKOFF_SECONDS = 2


