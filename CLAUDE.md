# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run (requires proxy for Binance API access from China)
.venv/bin/python main.py                          # accumulation mode (default)
.venv/bin/python main.py --mode divergence         # MACD divergence mode
.venv/bin/python main.py --mode new                # new coin observation
.venv/bin/python main.py --backtest --days 180     # backtest with 180d history
.venv/bin/python main.py --track                   # show tracked symbols
.venv/bin/python main.py --history ZIL/USDT        # single symbol history

# Scan history web UI (read-only browser for scanner.db scan_results)
.venv/bin/python -m history_ui                     # http://127.0.0.1:5050  (HISTORY_UI_HOST / HISTORY_UI_PORT)

# Test
.venv/bin/pytest tests/ -v                         # all tests
.venv/bin/pytest tests/test_detector.py -v         # single file
.venv/bin/pytest tests/test_detector.py::TestVolumeDecline::test_volume_declining_passes -v  # single test

# Install
.venv/bin/pip install -r requirements.txt
```

## Architecture

Binance crypto scanner with 3 scan modes + backtest, running as a CLI tool.

**Data pipeline (all modes):**
```
config.yaml → load_config()
  → fetch_futures_symbols()     # Binance USDM ∩ spot intersection
  → fetch_klines_batch()        # daily OHLCV via ccxt
  → detect / score              # mode-specific detection
  → rank_results()              # top_n by score
  → generate_signals()          # entry/stop-loss/take-profit
  → save_scan() + results/      # SQLite + JSON/TXT output
```

**scanner/ module responsibilities:**
- `kline.py` — Binance API gateway (ccxt). Two instances: `ccxt.binance` (spot) + `ccxt.binanceusdm` (futures). Proxy via `httpsProxy` (ccxt 4.x format).
- `detector.py` — Accumulation pattern: 4 checks (volume decline, downtrend slope, drop range, daily volatility cap). Tries windows from max→min days.
- `divergence.py` — MACD divergence: finds pivot pairs where price and DIF diverge. Scores by strength (0.4) + histogram confirmation (0.3) + time reasonableness (0.3).
- `scorer.py` — Accumulation scoring: volume (0.3) + drop tempering (0.25) + R² (0.25) + smoothness (0.2).
- `signal.py` — `SignalConfig` + `TradeSignal` dataclasses. Generates entry/SL/TP from score-filtered matches. Bearish signals reverse SL/TP.
- `backtest.py` — Sliding window historical detection with 3/7/14/30d return stats. Deduplicates within window_max_days.
- `tracker.py` — SQLite (`scanner.db`): `scans` + `scan_results` tables; `query_scan_results()` for paginated history UI.
- `history_ui/` — Flask + Jinja2 local page to browse scan history (`python -m history_ui`).
- `coingecko.py` — Market cap pagination with rate limit handling.
- `new_coin.py` — Recent listings discovery via binary search for first candle date.
- `listing_intel.py` — L2 enrichment: Binance CMS announcements, DexScreener chain pools, rule-based DD scoring.

**main.py** (627 lines) — CLI entry point with argparse. Four execution paths: `run()`, `run_divergence()`, `run_new_coin_observation()`, `run_backtest_cli()`.

## Key Conventions

- All exchange data flows through `scanner/kline.py` global singleton pattern (`_exchange`, `_usdm`). Call `set_proxy()` before any API use.
- ccxt 4.x uses `httpsProxy` (not the old `proxies` dict). Cannot set both `httpProxy` and `httpsProxy`.
- Detection functions return dataclass results (`DetectionResult`, `DivergenceResult`). `matched=True` / `divergence_type != "none"` means pattern found.
- Scores are floats in [0, 1]. Signal threshold is `min_score` in config (default 0.6).
- Tests use `_make_klines()` helper to construct synthetic DataFrames. No external API calls in tests.
- Config has sensible defaults in code; YAML overrides are optional per-field.
- Results output to `results/` directory as timestamped JSON + TXT pairs.

## Language

User prefers Chinese (Simplified) for all communication.
