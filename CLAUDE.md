# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run — subcommand style (requires proxy for Binance API access from China)
.venv/bin/python main.py scan                      # divergence mode (default)
.venv/bin/python main.py scan --mode accumulation   # accumulation mode
.venv/bin/python main.py scan --mode breakout       # breakout mode
.venv/bin/python main.py backtest --days 180        # backtest with 180d history
.venv/bin/python main.py track                      # show tracked symbols
.venv/bin/python main.py history ZIL/USDT           # single symbol history
.venv/bin/python main.py serve                      # daemon mode with scheduler
.venv/bin/python main.py stats                      # performance stats
.venv/bin/python main.py optimize run               # Optuna param optimization
.venv/bin/python main.py optimize report            # view optimized params
.venv/bin/python main.py retrain                    # retrain ML model

# Sentiment (舆情分析)
.venv/bin/python main.py sentiment scan             # 手动采集舆情
.venv/bin/python main.py sentiment status            # 查看情绪指标

# Portfolio (组合管理)
.venv/bin/python main.py portfolio status            # 查看策略权重
.venv/bin/python main.py portfolio rebalance         # 手动再平衡
.venv/bin/python main.py portfolio report            # 生成绩效报告

# Legacy flag style still works (with deprecation notice):
.venv/bin/python main.py --mode divergence          # → scan --mode divergence
.venv/bin/python main.py --backtest --days 180      # → backtest --days 180

# API server (FastAPI + React SPA)
.venv/bin/python -m api                            # http://127.0.0.1:8000  (API_HOST / API_PORT)
cd web && npm run dev                              # frontend dev server (Vite, port 5173, proxies /api to 8000)
# OpenAPI docs: http://127.0.0.1:8000/docs

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
- `api/` — FastAPI app with scanner/sentiment/portfolio JSON endpoints and React SPA serving (`python -m api`).
- `coingecko.py` — Market cap pagination with rate limit handling.
- `new_coin.py` — Recent listings discovery via binary search for first candle date.
- `listing_intel.py` — L2 enrichment: Binance CMS announcements, DexScreener chain pools, rule-based DD scoring.

**sentiment/ module responsibilities:**
- `models.py` — `SentimentItem`, `SentimentSignal` frozen dataclasses.
- `store.py` — SQLite persistence for sentiment items and signals.
- `sources/twitter.py` — Twitter/X scraping via snscrape.
- `sources/telegram.py` — Telegram channel monitoring via Telethon.
- `sources/news.py` — CryptoPanic API + RSS aggregation.
- `sources/onchain.py` — Etherscan whale transfer tracking.
- `analyzer.py` — VADER + crypto lexicon + onchain rule engine.
- `aggregator.py` — Multi-source fusion → `SentimentSignal`; `compute_boost()` for score adjustment.

**portfolio/ module responsibilities:**
- `models.py` — `StrategyResult` (frozen), `PortfolioState` (mutable) dataclasses.
- `store.py` — SQLite for NAV history, strategy weights, risk events.
- `allocator.py` — Riskfolio-Lib CVaR weight optimization.
- `risk.py` — Three-layer risk control (position/strategy/portfolio level).
- `rebalancer.py` — Drift detection + adjustment calculation.
- `tracker.py` — QuantStats performance reports (HTML).

**main.py** — CLI entry point with argparse subcommands. Execution paths include scanning, backtesting, sentiment analysis, portfolio management, and serve mode.

## Key Conventions

- All exchange data flows through `scanner/kline.py` global singleton pattern (`_exchange`, `_usdm`). Call `set_proxy()` before any API use.
- ccxt 4.x uses `httpsProxy` (not the old `proxies` dict). Cannot set both `httpProxy` and `httpsProxy`.
- Detection functions return dataclass results (`DetectionResult`, `DivergenceResult`). `matched=True` / `divergence_type != "none"` means pattern found.
- Scores are floats in [0, 1]. Signal threshold is `min_score` in config (default 0.6).
- Tests use `_make_klines()` helper to construct synthetic DataFrames. No external API calls in tests.
- Config has sensible defaults in code; YAML overrides are optional per-field.
- Results output to `results/` directory as timestamped JSON + TXT pairs.
- Sentiment boost (±20% max) adjusts scanner scores when sentiment module is enabled. Falls back to boost=0 if unavailable.
- Portfolio weights are optimized via CVaR and persisted in SQLite. Three-layer risk control halts trading on excessive drawdown.

## Language

User prefers Chinese (Simplified) for all communication.
