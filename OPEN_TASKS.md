# Browser Harness Open Tasks

Durable task list for the Browser Harness toolchain and agents-first workspace.

## Active

- **[Backtesting] Bulk Historical Data Ingestion** `[planned]`
  - Use `tv_ohlcv_scraper.py` to fetch multi-year data for core symbols.
  - Target Symbols: SPY, QQQ, TSLA, BTCUSD, ETHUSD.
  - Timespan: Max available (10Y+).
  - Storage: `agent-workspace/data/tv_ohlcv/`.

- **[Scraper] Add 24h interval support** `[planned]`
  - Distinguish between 1D (Exchange daily) and 24h (Rolling window).
  - Implement 24h stats via 1h bar aggregation or Screener API.

- **[Tooling] BH connection health audit** `[high]`
  - Fix `browser-harness --doctor` false negatives on connection state.
  - Improve error reporting for headless Way 2 sessions.

## Recently Completed

- **TradingView OHLCV Scraper Pilot** (2026-05-15)
  - Created `tv_ohlcv_scraper.py`.
  - Implemented 65m local resampling.
  - Verified bulk fetching for NNE, ETHUSD, QQQ, SPY, TSLA.
