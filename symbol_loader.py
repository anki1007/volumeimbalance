import csv
import requests
from io import StringIO
from config import GITHUB_SYMBOLS_RAW_URL, SYMBOL_LIMIT

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/plain"
}

def load_symbols():
    r = requests.get(GITHUB_SYMBOLS_RAW_URL, headers=HEADERS, timeout=10)
    r.raise_for_status()

    csv_file = StringIO(r.text)
    reader = csv.DictReader(csv_file)

    symbols = []
    for row in reader:
        symbols.append({
            "symbol": row["Symbol"].strip(),
            "sector": row.get("Industry", "NA").strip()
        })
        if len(symbols) >= SYMBOL_LIMIT:
            break

    return symbols
