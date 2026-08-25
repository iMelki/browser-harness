"""
advanced_tv_scraper.py
======================
High-durability TradingView OHLCV scraper with jitter, backoff, and manifest tracking.

Features:
- Jittered delays: 77s to 777s between requests.
- Exponential backoff: starting at 30m (1800s) on rate limit.
- Random bars: 555 to 3333 per request.
- Manifest tracking: persists inventory in data_manifest.json.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd

try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    print("ERROR: tvDatafeed is not installed.")
    sys.exit(1)

# Configuration from tv_ohlcv_scraper.py
SYMBOLS: dict[str, tuple[str, str]] = {
    "NNE":    ("NASDAQ", "NNE"),
    "ETHUSD": (os.environ.get("ETHUSD_EXCHANGE", "BINANCE"), "ETHUSDT"),
    "QQQ":    ("NASDAQ", "QQQ"),
    "SPY":    ("AMEX",   "SPY"),
    "TSLA":   ("NASDAQ", "TSLA"),
}

INTERVALS: dict[str, Interval] = {
    "1W":  Interval.in_weekly,
    "1D":  Interval.in_daily,
    "4H":  Interval.in_4_hour,
    "65m": Interval.in_1_minute,
    "15m": Interval.in_15_minute,
}

RESAMPLE_65M_FROM_1M = True

class DataManifest:
    def __init__(self, manifest_path: Path):
        self.path = manifest_path
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def update(self, key: str, symbol: str, interval: str, df: pd.DataFrame):
        if df.empty:
            return
        
        # Standardise index if it's not already datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        earliest = df.index.min().strftime("%Y-%m-%d %H:%M:%S")
        latest = df.index.max().strftime("%Y-%m-%d %H:%M:%S")
        
        entry = self.data.get(key, {
            "symbol": symbol,
            "interval": interval,
            "earliest_date": earliest,
            "latest_date": latest,
            "bar_count": 0
        })

        # Update dates
        if earliest < entry["earliest_date"]:
            entry["earliest_date"] = earliest
        if latest > entry["latest_date"]:
            entry["latest_date"] = latest
        
        entry["bar_count"] = len(df) # In a more complex version, we'd count unique bars
        entry["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.data[key] = entry
        self.save()

def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = df.sort_index()
    resampled = df.resample(rule, closed="left", label="left").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    return resampled

def fetch_with_safety(
    tv: TvDatafeed,
    symbol_key: str,
    interval_key: str,
    manifest: DataManifest,
    out_dir: Path,
    backoff_time: int = 1800 # 30 mins
):
    exchange, ticker = SYMBOLS[symbol_key]
    tv_interval = INTERVALS[interval_key]
    
    # Random number of bars between 555 and 3333
    n_bars = random.randint(555, 3333)
    
    is_65m = (interval_key == "65m")
    fetch_interval = Interval.in_1_minute if (is_65m and RESAMPLE_65M_FROM_1M) else tv_interval
    fetch_bars = n_bars * 65 + 500 if (is_65m and RESAMPLE_65M_FROM_1M) else n_bars

    print(f"  [SAFETY] Fetching {symbol_key} @ {interval_key} ({n_bars} random bars)...")

    attempts = 0
    while attempts < 3:
        try:
            df = tv.get_hist(
                symbol=ticker,
                exchange=exchange,
                interval=fetch_interval,
                n_bars=fetch_bars,
            )
            
            if df is None or df.empty:
                print(f"    Warning: No data returned for {symbol_key}")
                return None

            if is_65m and RESAMPLE_65M_FROM_1M:
                df = resample_ohlcv(df, "65min")
                df = df.tail(n_bars)

            df.index.name = "datetime"
            df = df.rename(columns=str.lower)
            
            # Save CSV
            out_path = out_dir / f"{symbol_key}_{interval_key}.csv"
            df.to_csv(out_path)
            
            # Update manifest
            manifest.update(f"{symbol_key}_{interval_key}", symbol_key, interval_key, df)
            
            print(f"    OK: {len(df)} bars saved to {out_path.name}")
            return df

        except Exception as e:
            if "429" in str(e) or "403" in str(e) or "rate limit" in str(e).lower():
                wait = backoff_time * (2 ** attempts)
                print(f"    RATE LIMIT DETECTED. Backing off for {wait/60:.1f} minutes...")
                time.sleep(wait)
                attempts += 1
            else:
                print(f"    Error: {e}")
                return None
    return None

def main():
    parser = argparse.ArgumentParser(description="Advanced TV Scraper with safety features")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS.keys()))
    parser.add_argument("--intervals", nargs="+", default=list(INTERVALS.keys()))
    parser.add_argument("--out-dir", default="data/tv_ohlcv")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = DataManifest(out_dir / "data_manifest.json")

    tv = TvDatafeed(
        username=os.environ.get("TV_USERNAME", ""),
        password=os.environ.get("TV_PASSWORD", "")
    )

    print(f"Starting advanced ingestion for {args.symbols}...")
    
    for symbol in args.symbols:
        for interval in args.intervals:
            fetch_with_safety(tv, symbol, interval, manifest, out_dir)
            
            # Jittered delay between 77s and 777s
            delay = random.randint(77, 777)
            print(f"  [JITTER] Sleeping for {delay}s before next request...")
            time.sleep(delay)

if __name__ == "__main__":
    main()
