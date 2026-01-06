import csv, os

BASE = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE, "data", "symbols.csv")

def load_symbols():
    symbols = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbols.append(row)
    return symbols
