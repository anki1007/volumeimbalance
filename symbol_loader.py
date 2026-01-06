import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "data", "symbols.csv")

def load_symbols():
    symbols = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("Symbol", "").strip().upper()
            sector = row.get("Industry", "NA").strip()

            # Only EQ series (extra safety)
            if row.get("Series", "").strip() != "EQ":
                continue

            if sym:
                symbols.append({
                    "symbol": sym,
                    "sector": sector
                })

    return symbols
