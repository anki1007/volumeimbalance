import csv

def load_symbols():
    symbols = []
    with open("data/symbols.csv", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbols.append({
                "symbol": row["symbol"],
                "sector": row["sector"]
            })
    return symbols
