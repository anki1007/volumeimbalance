# symbol_loader.py

import pandas as pd
import requests
from config import GITHUB_SYMBOLS_RAW_URL, MAX_SYMBOLS

def load_symbols():
    """
    Load symbols + sector from GitHub CSV
    """
    df = pd.read_csv(GITHUB_SYMBOLS_RAW_URL)
    df = df.dropna(subset=["Symbol", "Industry"])
    df = df.rename(columns={"Industry": "Sector"})
    return df[["Symbol", "Sector"]].head(MAX_SYMBOLS).to_dict("records")
