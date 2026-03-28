# 币种筛选系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从全市场小市值币种中筛选出"底部蓄力"形态的币种（缩量+缓跌+小幅+持续1-2周）

**Architecture:** CoinGecko免费API按市值初筛 → ccxt从Binance拉日K线 → 形态检测引擎逐币分析 → 评分排序 → CLI表格输出

**Tech Stack:** Python 3.13, ccxt, requests, pandas, numpy, tabulate, pyyaml

---

## File Map

| File | Responsibility |
|------|---------------|
| `config.yaml` | 所有可配置参数 |
| `scanner/__init__.py` | 包导出 |
| `scanner/coingecko.py` | CoinGecko API调用，市值筛选，返回币种列表 |
| `scanner/kline.py` | ccxt Binance K线拉取，返回DataFrame |
| `scanner/detector.py` | 四项形态条件检测，返回是否命中+各项指标值 |
| `scanner/scorer.py` | 评分计算，加权排序 |
| `main.py` | CLI入口，串联全流程，tabulate输出 |
| `tests/test_detector.py` | 形态检测单元测试 |
| `tests/test_scorer.py` | 评分逻辑单元测试 |
| `requirements.txt` | 依赖列表 |

---

### Task 1: 项目脚手架 — config.yaml + requirements.txt + scanner包

**Files:**
- Create: `config.yaml`
- Create: `requirements.txt`
- Create: `scanner/__init__.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
ccxt>=4.0.0
requests>=2.31.0
pandas>=2.2.0
numpy>=1.26.0
tabulate>=0.9.0
pyyaml>=6.0.0
pytest>=8.0.0
```

- [ ] **Step 2: 创建 config.yaml**

```yaml
scanner:
  max_market_cap: 100000000    # 市值上限（美元），默认1亿
  window_min_days: 7           # 检测窗口最小天数
  window_max_days: 14          # 检测窗口最大天数
  volume_ratio: 0.5            # 缩量阈值（后期量/前期量）
  drop_min: 0.05               # 最小跌幅 5%
  drop_max: 0.15               # 最大跌幅 15%
  max_daily_change: 0.05       # 单日最大涨跌幅 5%
  top_n: 20                    # 输出前N个结果
```

- [ ] **Step 3: 创建 scanner/__init__.py**

```python
from scanner.coingecko import fetch_small_cap_coins
from scanner.kline import fetch_klines
from scanner.detector import detect_pattern
from scanner.scorer import score_and_rank
```

- [ ] **Step 4: 安装依赖**

Run: `pip install -r requirements.txt`

- [ ] **Step 5: Commit**

```bash
git add config.yaml requirements.txt scanner/__init__.py
git commit -m "feat: project scaffold — config, deps, scanner package"
```

---

### Task 2: 形态检测引擎 — detector.py（TDD）

**Files:**
- Create: `scanner/detector.py`
- Create: `tests/test_detector.py`

- [ ] **Step 1: 写失败测试 — 缩量检测**

创建 `tests/test_detector.py`:

```python
import pandas as pd
import numpy as np
from scanner.detector import detect_pattern, DetectionResult


def _make_klines(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造测试用K线DataFrame"""
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


class TestVolumeDecline:
    """缩量判断测试"""

    def test_volume_declining_passes(self):
        # 前7天量大，后7天量小（后期均量 < 前期均量 * 0.5）
        volumes = [1000] * 7 + [300] * 7
        closes = [100 - i * 0.5 for i in range(14)]  # 缓慢下跌
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.volume_pass is True

    def test_volume_not_declining_fails(self):
        # 前后量一样，不缩量
        volumes = [1000] * 14
        closes = [100 - i * 0.5 for i in range(14)]
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.volume_pass is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.detector'`

- [ ] **Step 3: 写失败测试 — 下跌趋势 + 跌幅范围 + 缓慢确认**

追加到 `tests/test_detector.py`:

```python
class TestDowntrend:
    """下跌趋势测试"""

    def test_downtrend_passes(self):
        closes = [100 - i * 0.8 for i in range(14)]  # 缓慢下跌
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.trend_pass is True

    def test_uptrend_fails(self):
        closes = [100 + i * 0.8 for i in range(14)]  # 上涨
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.trend_pass is False


class TestDropRange:
    """跌幅范围测试"""

    def test_drop_in_range_passes(self):
        # 14天从100跌到90，跌幅10%，在5%-15%范围内
        closes = [100 - i * (10 / 13) for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.drop_pass is True

    def test_drop_too_large_fails(self):
        # 14天从100跌到70，跌幅30%，超出范围
        closes = [100 - i * (30 / 13) for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.drop_pass is False


class TestSlowDecline:
    """缓慢确认测试（单日涨跌幅不超限）"""

    def test_slow_decline_passes(self):
        # 每天跌约0.7%，远低于5%限制
        closes = [100 - i * 0.7 for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.slow_pass is True

    def test_spike_day_fails(self):
        # 大部分天缓跌，但第7天暴跌10%
        closes = [100 - i * 0.3 for i in range(14)]
        closes[7] = closes[6] * 0.90  # 单日暴跌10%
        # 后续价格从暴跌后继续缓跌
        for i in range(8, 14):
            closes[i] = closes[7] - (i - 7) * 0.3
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.slow_pass is False


class TestFullPattern:
    """完整形态命中测试"""

    def test_perfect_pattern_matches(self):
        # 构造完美的底部蓄力形态
        closes = [100 - i * 0.7 for i in range(14)]  # 缓跌约9.8%
        volumes = [1000] * 7 + [300] * 7  # 明显缩量
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.matched is True

    def test_no_match_when_volume_flat(self):
        closes = [100 - i * 0.7 for i in range(14)]
        volumes = [1000] * 14  # 不缩量
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.matched is False
```

- [ ] **Step 4: 实现 detector.py**

创建 `scanner/detector.py`:

```python
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DetectionResult:
    """形态检测结果"""
    volume_pass: bool       # 缩量通过
    trend_pass: bool        # 下跌趋势通过
    drop_pass: bool         # 跌幅范围通过
    slow_pass: bool         # 缓慢确认通过
    matched: bool           # 四项全部通过
    volume_ratio: float     # 实际缩量比（后期均量/前期均量）
    drop_pct: float         # 实际跌幅百分比
    r_squared: float        # 趋势线性回归R²
    max_daily_pct: float    # 窗口内最大单日涨跌幅
    window_days: int        # 实际使用的窗口天数


def detect_pattern(
    df: pd.DataFrame,
    window_min_days: int = 7,
    window_max_days: int = 14,
    volume_ratio: float = 0.5,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> DetectionResult:
    """对K线数据做底部蓄力形态检测。

    尝试从 window_max_days 到 window_min_days 的不同窗口，
    取第一个四项全部通过的窗口；若都不通过，取 window_max_days 的结果。
    """
    best = None
    for window in range(window_max_days, window_min_days - 1, -1):
        result = _detect_window(df, window, volume_ratio, drop_min, drop_max, max_daily_change)
        if result.matched:
            return result
        if best is None:
            best = result
    return best


def _detect_window(
    df: pd.DataFrame,
    window: int,
    volume_ratio: float,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
) -> DetectionResult:
    """在固定窗口大小下检测形态"""
    tail = df.tail(window).copy()
    closes = tail["close"].values.astype(float)
    volumes = tail["volume"].values.astype(float)

    # 1. 缩量判断：前半段 vs 后半段
    mid = len(volumes) // 2
    early_avg = np.mean(volumes[:mid])
    late_avg = np.mean(volumes[mid:])
    actual_vol_ratio = late_avg / early_avg if early_avg > 0 else 1.0
    vol_pass = actual_vol_ratio < volume_ratio

    # 2. 下跌趋势：线性回归斜率为负
    x = np.arange(len(closes), dtype=float)
    slope, intercept = np.polyfit(x, closes, 1)
    ss_res = np.sum((closes - (slope * x + intercept)) ** 2)
    ss_tot = np.sum((closes - np.mean(closes)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    trend_pass = slope < 0

    # 3. 跌幅范围
    max_close = np.max(closes)
    min_close = np.min(closes)
    drop_pct = (max_close - min_close) / max_close if max_close > 0 else 0.0
    drop_pass = drop_min <= drop_pct <= drop_max

    # 4. 缓慢确认：单日涨跌幅不超限
    daily_returns = np.abs(np.diff(closes) / closes[:-1])
    max_daily_pct = float(np.max(daily_returns)) if len(daily_returns) > 0 else 0.0
    slow_pass = max_daily_pct <= max_daily_change

    matched = vol_pass and trend_pass and drop_pass and slow_pass

    return DetectionResult(
        volume_pass=vol_pass,
        trend_pass=trend_pass,
        drop_pass=drop_pass,
        slow_pass=slow_pass,
        matched=matched,
        volume_ratio=actual_vol_ratio,
        drop_pct=drop_pct,
        r_squared=r_squared,
        max_daily_pct=max_daily_pct,
        window_days=window,
    )
```

- [ ] **Step 5: 运行测试确认全部通过**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add scanner/detector.py tests/test_detector.py
git commit -m "feat: pattern detector with TDD — volume/trend/drop/slow checks"
```

---

### Task 3: 评分引擎 — scorer.py（TDD）

**Files:**
- Create: `scanner/scorer.py`
- Create: `tests/test_scorer.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scorer.py`:

```python
from scanner.detector import DetectionResult
from scanner.scorer import score_result, rank_results


class TestScoring:
    def test_perfect_pattern_high_score(self):
        result = DetectionResult(
            volume_pass=True, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=True,
            volume_ratio=0.3,      # 强缩量
            drop_pct=0.10,         # 正好10%，区间中心
            r_squared=0.95,        # 高R²
            max_daily_pct=0.01,    # 很平稳
            window_days=14,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score > 0.7

    def test_weak_pattern_low_score(self):
        result = DetectionResult(
            volume_pass=True, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=True,
            volume_ratio=0.48,     # 刚过阈值
            drop_pct=0.14,         # 接近上限
            r_squared=0.3,         # 低R²
            max_daily_pct=0.045,   # 接近限制
            window_days=7,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score < 0.5

    def test_unmatched_scores_zero(self):
        result = DetectionResult(
            volume_pass=False, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=False,
            volume_ratio=0.8, drop_pct=0.10, r_squared=0.9,
            max_daily_pct=0.02, window_days=14,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score == 0.0


class TestRanking:
    def test_rank_by_score_descending(self):
        items = [
            {"symbol": "AAA/USDT", "score": 0.5},
            {"symbol": "BBB/USDT", "score": 0.9},
            {"symbol": "CCC/USDT", "score": 0.7},
        ]
        ranked = rank_results(items, top_n=3)
        assert [r["symbol"] for r in ranked] == ["BBB/USDT", "CCC/USDT", "AAA/USDT"]

    def test_rank_top_n(self):
        items = [
            {"symbol": "A", "score": 0.9},
            {"symbol": "B", "score": 0.8},
            {"symbol": "C", "score": 0.7},
        ]
        ranked = rank_results(items, top_n=2)
        assert len(ranked) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 scorer.py**

创建 `scanner/scorer.py`:

```python
from scanner.detector import DetectionResult


def score_result(
    result: DetectionResult,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> float:
    """对检测结果计算综合评分，范围[0, 1]。未命中返回0。"""
    if not result.matched:
        return 0.0

    # 缩量程度 (权重0.3): 1 - ratio，越小越好
    vol_score = max(0.0, min(1.0, 1.0 - result.volume_ratio))

    # 跌幅温和度 (权重0.25): 越接近区间中心越高
    mid = (drop_min + drop_max) / 2
    half_range = (drop_max - drop_min) / 2
    drop_score = max(0.0, 1.0 - abs(result.drop_pct - mid) / half_range)

    # 趋势稳定性 (权重0.25): R²值
    trend_score = max(0.0, min(1.0, result.r_squared))

    # 波动平稳度 (权重0.2): 最大单日涨跌幅越小越好
    slow_score = max(0.0, min(1.0, 1.0 - result.max_daily_pct / max_daily_change))

    return vol_score * 0.3 + drop_score * 0.25 + trend_score * 0.25 + slow_score * 0.2


def rank_results(items: list[dict], top_n: int = 20) -> list[dict]:
    """按score降序排列，取前top_n个。"""
    sorted_items = sorted(items, key=lambda x: x["score"], reverse=True)
    return sorted_items[:top_n]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/scorer.py tests/test_scorer.py
git commit -m "feat: scorer with weighted ranking — volume/drop/trend/volatility"
```

---

### Task 4: CoinGecko 市值筛选 — coingecko.py

**Files:**
- Create: `scanner/coingecko.py`

- [ ] **Step 1: 实现 coingecko.py**

```python
import time

import requests


COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def fetch_small_cap_coins(max_market_cap: float = 100_000_000) -> list[dict]:
    """从CoinGecko拉取市值低于阈值的币种列表。

    Returns:
        list of dict, each with keys:
            - id: CoinGecko币种ID
            - symbol: 币种符号（大写）
            - name: 币种名称
            - market_cap: 市值（美元）
    """
    coins = []
    page = 1
    while True:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break

        for coin in data:
            mc = coin.get("market_cap") or 0
            if mc <= 0:
                continue
            if mc > max_market_cap:
                continue
            coins.append({
                "id": coin["id"],
                "symbol": coin["symbol"].upper(),
                "name": coin["name"],
                "market_cap": mc,
            })

        # 如果本页所有币市值都大于阈值且不为0，继续翻页
        # 如果本页不足250条，说明到头了
        if len(data) < 250:
            break

        page += 1
        time.sleep(2)  # CoinGecko限速：30次/分钟

    return coins
```

- [ ] **Step 2: Commit**

```bash
git add scanner/coingecko.py
git commit -m "feat: CoinGecko small-cap coin fetcher with rate limiting"
```

---

### Task 5: Binance K线拉取 — kline.py

**Files:**
- Create: `scanner/kline.py`

- [ ] **Step 1: 实现 kline.py**

```python
import asyncio
import time

import ccxt
import pandas as pd


def fetch_klines(symbol: str, days: int = 30) -> pd.DataFrame | None:
    """从Binance拉取日K线数据。

    Args:
        symbol: 交易对，如 "BTC/USDT"
        days: 拉取天数

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        如果交易对不存在返回None
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=days)
    except ccxt.BadSymbol:
        return None
    except ccxt.ExchangeError:
        return None
    finally:
        exchange.close()

    if not ohlcv:
        return None

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_klines_batch(symbols: list[str], days: int = 30, delay: float = 0.5) -> dict[str, pd.DataFrame]:
    """批量拉取多个交易对的K线。

    Args:
        symbols: 交易对列表
        days: 拉取天数
        delay: 每次请求间隔秒数

    Returns:
        dict mapping symbol -> DataFrame (跳过失败的)
    """
    results = {}
    for symbol in symbols:
        df = fetch_klines(symbol, days)
        if df is not None and len(df) >= 7:  # 至少7天数据才有分析价值
            results[symbol] = df
        time.sleep(delay)
    return results
```

- [ ] **Step 2: Commit**

```bash
git add scanner/kline.py
git commit -m "feat: Binance kline fetcher via ccxt with batch support"
```

---

### Task 6: CLI 入口 — main.py

**Files:**
- Create: `main.py`

- [ ] **Step 1: 实现 main.py**

```python
import argparse
import sys
import time

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_small_cap_coins
from scanner.kline import fetch_klines_batch
from scanner.detector import detect_pattern
from scanner.scorer import score_result, rank_results


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f).get("scanner", {})


def run(config: dict, top_n: int | None = None):
    top_n = top_n or config.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: CoinGecko 市值筛选
    print(f"[1/3] 从CoinGecko拉取市值 < ${max_market_cap / 1e6:.0f}M 的币种...")
    coins = fetch_small_cap_coins(max_market_cap)
    print(f"       找到 {len(coins)} 个小市值币种")

    if not coins:
        print("没有找到符合条件的币种。")
        return

    # Step 2: 构建Binance交易对并拉K线
    symbols = [f"{c['symbol']}/USDT" for c in coins]
    coin_map = {f"{c['symbol']}/USDT": c for c in coins}

    print(f"[2/3] 从Binance拉取K线数据（约{len(symbols)}个交易对）...")
    klines = fetch_klines_batch(symbols, days=30, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 形态检测 + 评分
    print("[3/3] 形态检测中...")
    results = []
    for symbol, df in klines.items():
        detection = detect_pattern(
            df,
            window_min_days=config.get("window_min_days", 7),
            window_max_days=config.get("window_max_days", 14),
            volume_ratio=config.get("volume_ratio", 0.5),
            drop_min=config.get("drop_min", 0.05),
            drop_max=config.get("drop_max", 0.15),
            max_daily_change=config.get("max_daily_change", 0.05),
        )
        if not detection.matched:
            continue
        score = score_result(
            detection,
            drop_min=config.get("drop_min", 0.05),
            drop_max=config.get("drop_max", 0.15),
            max_daily_change=config.get("max_daily_change", 0.05),
        )
        coin_info = coin_map.get(symbol, {})
        results.append({
            "symbol": symbol,
            "market_cap_m": coin_info.get("market_cap", 0) / 1e6,
            "drop_pct": detection.drop_pct,
            "volume_ratio": detection.volume_ratio,
            "window_days": detection.window_days,
            "score": score,
        })

    ranked = rank_results(results, top_n=top_n)

    if not ranked:
        print("\n未找到符合底部蓄力形态的币种。")
        return

    # 输出表格
    table_data = []
    for i, r in enumerate(ranked, 1):
        table_data.append([
            i,
            r["symbol"],
            f"{r['market_cap_m']:.1f}",
            f"{r['drop_pct'] * 100:.1f}%",
            f"{r['volume_ratio']:.2f}",
            r["window_days"],
            f"{r['score']:.2f}",
        ])

    headers = ["排名", "币种", "市值(M$)", "跌幅", "缩量比", "天数", "评分"]
    print(f"\n找到 {len(ranked)} 个底部蓄力形态币种:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def main():
    parser = argparse.ArgumentParser(description="币种底部蓄力形态筛选器")
    parser.add_argument("--top", type=int, help="输出前N个结果")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    run(config, top_n=args.top)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: CLI entry point — scan, detect, score, display"
```

---

### Task 7: 集成验证

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 手动冒烟测试**

Run: `python main.py --top 5`
Expected: 程序正常运行，输出表格或"未找到"提示（取决于当前市场状态）

- [ ] **Step 3: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: integration fixes from smoke test"
```
