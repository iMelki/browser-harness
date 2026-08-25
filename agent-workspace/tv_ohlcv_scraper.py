"""
tv_ohlcv_scraper.py
===================
Bulk OHLCV historical data fetcher for the Milky backtesting service.

Uses tvDatafeed — the only reliable way to pull multi-bar historical OHLCV from
TradingView without a paid API key. tvDatafeed reverse-engineers the same
authenticated WebSocket session that the TV charting UI uses.

Symbols  : NNE, ETHUSD, QQQ, SPY, TSLA
Timeframes: 1W, 1D, 4H, 65m, 15m

NOTE on the "24h" timeframe:
  TradingView does not have a "24H" bar interval. The closest equivalents are:
    - 1D  (daily bars — standard for all instruments)
    - 4H  (4-hour bars — highest sub-daily standard bar)
  If you mean the 24-hour rolling performance window, use the screener API
  (change|1D column). This script maps "24h" -> "1D" as the intent.

NOTE on ETHUSD:
  TradingView has many ETHUSD feeds. This script defaults to BINANCE:ETHUSDT
  (deepest liquidity, most history). Override via ETHUSD_EXCHANGE env var.

Output: data/tv_ohlcv/<SYMBOL>_<INTERVAL>.csv  (one file per symbol×interval)

Requirements:
  pip install tvDatafeed pandas

Usage:
  python tv_ohlcv_scraper.py
  python tv_ohlcv_scraper.py --symbols NNE TSLA --intervals 1D 4H
  python tv_ohlcv_scraper.py --bars 500 --out-dir ./custom_out
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional
import pandas as pd

try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    print(
        "ERROR: tvDatafeed is not installed.\n"
        "Install with:\n"
        "  pip install git+https://github.com/rongardF/tvdatafeed.git pandas\n"
        "\n"
        "Note: the package name on pip is 'tvdatafeed' (lowercase) but the\n"
        "Python module inside is 'tvDatafeed' (camelCase). Both refer to the same thing.\n"
    )
    sys.exit(1)


# ── Symbol map ─────────────────────────────────────────────────────────────────
# Format: "DISPLAY_NAME": ("exchange", "ticker")
# NNE  = Nuvve Holding Corp (NASDAQ)
# ETHUSD = Ethereum/USD via Binance (deepest history)
# QQQ  = Invesco QQQ Trust (NASDAQ)
# SPY  = SPDR S&P 500 ETF (AMEX/NYSE Arca)
# TSLA = Tesla (NASDAQ)

SYMBOLS: dict[str, tuple[str, str]] = {
    "NNE":    ("NASDAQ", "NNE"),
    "ETHUSD": (os.environ.get("ETHUSD_EXCHANGE", "BINANCE"), "ETHUSDT"),
    "QQQ":    ("NASDAQ", "QQQ"),
    "SPY":    ("AMEX",   "SPY"),
    "TSLA":   ("NASDAQ", "TSLA"),
}

# ── Interval map ───────────────────────────────────────────────────────────────
# Maps human label -> tvDatafeed Interval enum
# "24h" is mapped to 1D (see module docstring above)
INTERVALS: dict[str, Interval] = {
    "1W":  Interval.in_weekly,
    "1D":  Interval.in_daily,
    "24h": Interval.in_daily,   # alias — see note above
    "4H":  Interval.in_4_hour,
    "65m": Interval.in_1_minute,  # placeholder — see note below
    "15m": Interval.in_15_minute,
}

# NOTE on 65m:
#   TradingView does not expose a 65-minute bar interval via the public API
#   surface that tvDatafeed uses. The available sub-hourly intervals are:
#     1m, 3m, 5m, 15m, 30m, 45m, 1H, 2H, 3H, 4H
#   65m is a chart-only custom interval available in the TV UI (Pine Script)
#   but not in the datafeed API.
#   Options:
#     (A) Fetch 1m bars and resample to 65m locally (most accurate, see below)
#     (B) Use 1H bars as a proxy
#   This script uses option A: fetch 1m and resample to 65m.
#   Change RESAMPLE_65M_FROM_1M = False to use 1H as proxy instead.

RESAMPLE_65M_FROM_1M = True


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample a 1-minute OHLCV DataFrame to an arbitrary frequency string.

    Args:
        df: DataFrame with DatetimeIndex and columns [open, high, low, close, volume]
        rule: pandas offset alias e.g. "65T" for 65-minute bars
    """
    df = df.sort_index()
    resampled = df.resample(rule, closed="left", label="left").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    return resampled


def fetch_symbol_interval(
    tv: TvDatafeed,
    symbol_key: str,
    interval_key: str,
    n_bars: int,
    out_dir: Path,
    delay: float = 1.2,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV for one symbol × interval combination.

    Returns the DataFrame written, or None on failure.
    """
    exchange, ticker = SYMBOLS[symbol_key]
    tv_interval = INTERVALS[interval_key]

    is_65m = (interval_key == "65m")
    fetch_interval = Interval.in_1_minute if (is_65m and RESAMPLE_65M_FROM_1M) else tv_interval
    # 1m has less history; fetch more bars to cover the same period after resampling
    fetch_bars = n_bars * 65 + 500 if (is_65m and RESAMPLE_65M_FROM_1M) else n_bars

    print(f"  Fetching {symbol_key} ({exchange}:{ticker}) @ {interval_key} ... ", end="", flush=True)

    try:
        df = tv.get_hist(
            symbol=ticker,
            exchange=exchange,
            interval=fetch_interval,
            n_bars=fetch_bars,
            fut_contract=None,
            extended_session=False,
        )
    except Exception as exc:
        print(f"FAILED ({exc})")
        return None

    if df is None or df.empty:
        print("EMPTY — symbol may not exist on this exchange")
        return None

    # Resample 1m -> 65m if needed
    if is_65m and RESAMPLE_65M_FROM_1M:
        df = resample_ohlcv(df, "65min")
        df = df.tail(n_bars)  # trim to requested bar count

    # Normalise column names
    df.index.name = "datetime"
    df = df.rename(columns=str.lower)

    # Write CSV
    filename = f"{symbol_key}_{interval_key}.csv"
    out_path = out_dir / filename
    df.to_csv(out_path)
    print(f"OK  ({len(df)} bars -> {out_path.name})")

    time.sleep(delay)  # be polite to TradingView servers
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk OHLCV downloader for the Milky backtesting service"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=list(SYMBOLS.keys()),
        help=f"Symbols to fetch. Choices: {list(SYMBOLS.keys())}"
    )
    parser.add_argument(
        "--intervals", nargs="+", default=list(INTERVALS.keys()),
        help=f"Intervals to fetch. Choices: {list(INTERVALS.keys())}"
    )
    parser.add_argument(
        "--bars", type=int, default=300,
        help="Number of bars to fetch per symbol/interval (default: 300)"
    )
    parser.add_argument(
        "--out-dir", default="data/tv_ohlcv",
        help="Output directory for CSV files (default: data/tv_ohlcv)"
    )
    parser.add_argument(
        "--username", default=os.environ.get("TV_USERNAME", ""),
        help="TradingView username (or set TV_USERNAME env var). Optional — more history when logged in."
    )
    parser.add_argument(
        "--password", default=os.environ.get("TV_PASSWORD", ""),
        help="TradingView password (or set TV_PASSWORD env var). Optional."
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validate inputs
    bad_symbols   = [s for s in args.symbols   if s not in SYMBOLS]
    bad_intervals = [i for i in args.intervals if i not in INTERVALS]
    if bad_symbols:
        print(f"ERROR: Unknown symbols: {bad_symbols}. Valid: {list(SYMBOLS.keys())}")
        sys.exit(1)
    if bad_intervals:
        print(f"ERROR: Unknown intervals: {bad_intervals}. Valid: {list(INTERVALS.keys())}")
        sys.exit(1)

    # Connect to TradingView
    print("Connecting to TradingView...")
    if args.username and args.password:
        tv = TvDatafeed(username=args.username, password=args.password)
        print(f"  Authenticated as: {args.username}")
    else:
        tv = TvDatafeed()
        print("  Anonymous session (limited history — set TV_USERNAME/TV_PASSWORD for more bars)")

    # Deduplicate intervals (24h == 1D)
    seen_intervals: set[str] = set()
    run_intervals: list[str] = []
    for iv in args.intervals:
        key = f"{SYMBOLS.get('NNE', ('',''))[0]}:{iv}"  # unique per label
        actual_label = iv
        if iv == "24h" and "1D" in args.intervals:
            print(f"  Note: '24h' and '1D' map to the same TradingView interval — skipping '24h' duplicate")
            continue
        if actual_label not in seen_intervals:
            seen_intervals.add(actual_label)
            run_intervals.append(actual_label)

    total = len(args.symbols) * len(run_intervals)
    print(f"\nFetching {total} combinations: {args.symbols} × {run_intervals}")
    print(f"Output dir : {out_dir.resolve()}")
    print(f"Bars/combo : {args.bars}\n")

    if RESAMPLE_65M_FROM_1M and "65m" in run_intervals:
        print("  65m note: fetching 1m bars and resampling to 65m locally.\n")

    results: dict[str, str] = {}
    for symbol in args.symbols:
        for interval in run_intervals:
            key = f"{symbol}_{interval}"
            df = fetch_symbol_interval(tv, symbol, interval, args.bars, out_dir)
            results[key] = "ok" if df is not None else "failed"

    # Summary
    print("\n-- Summary ----------------------------------------------")
    ok     = [k for k, v in results.items() if v == "ok"]
    failed = [k for k, v in results.items() if v != "ok"]
    for k in ok:
        print(f"  [OK] {k}")
    for k in failed:
        print(f"  [FAIL] {k}  (check symbol/exchange or auth)")
    print(f"\n  {len(ok)}/{total} succeeded. CSVs at: {out_dir.resolve()}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
