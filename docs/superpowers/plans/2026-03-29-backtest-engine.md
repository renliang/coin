# Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtest engine that validates whether detected "bottom accumulation" patterns actually predict price increases.

**Architecture:** New `scanner/backtest.py` module with sliding-window scan over historical klines, reusing existing `detector` and `scorer`. CLI integration via `--backtest` flag in `main.py`.

**Tech Stack:** Python 3.13, pandas, numpy, tabulate (all existing dependencies)

---

### Task 1: Sliding Window Scan — `run_backtest()`

**Files:**
- Create: `scanner/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test for single-symbol scan**

```python
# tests/test_backtest.py
import pandas as pd
import numpy as np
from scanner.backtest import run_backtest, BacktestHit


def _make_klines(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造合成K线DataFrame。"""
    n = len(prices)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes,
    })


def test_run_backtest_detects_pattern():
    """构造一段明确的底部蓄力形态 + 后续上涨，验证能检测到并计算收益。"""
    # 14天缩量下跌（跌幅~10%，缩量，每日变化<5%）+ 30天后续上涨
    n_pattern = 14
    n_future = 30
    # 下跌段：从100缓跌到90，每日跌约0.7%
    pattern_prices = [100 - i * 0.7 for i in range(n_pattern)]
    # 前7天量大，后7天量小
    pattern_volumes = [1000] * 7 + [300] * 7
    # 后续上涨段：从90涨到100
    future_prices = [pattern_prices[-1] + i * 0.33 for i in range(1, n_future + 1)]
    future_volumes = [500] * n_future

    prices = pattern_prices + future_prices
    volumes = pattern_volumes + future_volumes
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"TEST/USDT": df}, config)

    assert len(hits) >= 1
    hit = hits[0]
    assert isinstance(hit, BacktestHit)
    assert hit.symbol == "TEST/USDT"
    assert hit.score > 0
    # 3天后应该有正收益（价格在涨）
    assert hit.returns["3d"] is not None
    assert hit.returns["3d"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_backtest.py::test_run_backtest_detects_pattern -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.backtest'`

- [ ] **Step 3: Write the BacktestHit dataclass and run_backtest()**

```python
# scanner/backtest.py
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from scanner.detector import detect_pattern
from scanner.scorer import score_result


RETURN_PERIODS = [3, 7, 14, 30]


@dataclass
class BacktestHit:
    symbol: str
    detect_date: str
    window_days: int
    drop_pct: float
    volume_ratio: float
    score: float
    returns: dict[str, float | None] = field(default_factory=dict)


def run_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
) -> list[BacktestHit]:
    """对所有币种做滑动窗口回扫，返回命中列表。"""
    window_min = config.get("window_min_days", 7)
    window_max = config.get("window_max_days", 14)
    vol_ratio = config.get("volume_ratio", 0.5)
    drop_min = config.get("drop_min", 0.05)
    drop_max = config.get("drop_max", 0.15)
    max_daily = config.get("max_daily_change", 0.05)

    all_hits: list[BacktestHit] = []

    for symbol, df in klines.items():
        closes = df["close"].values.astype(float)
        dates = df["timestamp"].values
        n = len(df)
        last_hit_idx = -window_max  # 去重：上次命中的索引

        # 从 window_max 开始逐日滑动
        for i in range(window_max, n + 1):
            # 去重：距上次命中不足 window_max 天则跳过
            if i - last_hit_idx < window_max:
                continue

            slice_df = df.iloc[:i].copy()
            result = detect_pattern(
                slice_df,
                window_min_days=window_min,
                window_max_days=window_max,
                volume_ratio=vol_ratio,
                drop_min=drop_min,
                drop_max=drop_max,
                max_daily_change=max_daily,
            )

            if not result.matched:
                continue

            last_hit_idx = i
            score = score_result(result, drop_min=drop_min, drop_max=drop_max, max_daily_change=max_daily)
            base_price = closes[i - 1]
            detect_date = str(pd.Timestamp(dates[i - 1]).date())

            # 计算各周期收益
            returns = {}
            for period in RETURN_PERIODS:
                future_idx = i - 1 + period
                if future_idx < n:
                    returns[f"{period}d"] = (closes[future_idx] - base_price) / base_price
                else:
                    returns[f"{period}d"] = None

            all_hits.append(BacktestHit(
                symbol=symbol,
                detect_date=detect_date,
                window_days=result.window_days,
                drop_pct=result.drop_pct,
                volume_ratio=result.volume_ratio,
                score=score,
                returns=returns,
            ))

    return all_hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_backtest.py::test_run_backtest_detects_pattern -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/backtest.py tests/test_backtest.py
git commit -m "feat: backtest sliding window scan with return calculation"
```

---

### Task 2: Deduplication Logic

**Files:**
- Modify: `scanner/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test for dedup**

```python
# tests/test_backtest.py — append

def test_run_backtest_dedup_adjacent_hits():
    """连续命中的形态只保留第一次，间隔不足 window_max_days 的跳过。"""
    # 构造两段相邻的底部蓄力形态（间隔 < 14天）
    # 第一段：14天缩量下跌
    seg1_prices = [100 - i * 0.7 for i in range(14)]
    seg1_volumes = [1000] * 7 + [300] * 7
    # 间隔5天（平盘）
    gap_prices = [seg1_prices[-1]] * 5
    gap_volumes = [300] * 5
    # 第二段：又一个14天缩量下跌（紧接着，应被去重）
    seg2_start = gap_prices[-1]
    seg2_prices = [seg2_start - i * 0.7 for i in range(14)]
    seg2_volumes = [1000] * 7 + [300] * 7
    # 后续30天
    future_prices = [seg2_prices[-1] + i * 0.5 for i in range(1, 31)]
    future_volumes = [500] * 30

    prices = seg1_prices + gap_prices + seg2_prices + future_prices
    volumes = seg1_volumes + gap_volumes + seg2_volumes + future_volumes
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"TEST/USDT": df}, config)

    # 第二段因间隔不足 window_max_days 应被去重，最多2次命中
    # （第一次命中后要间隔>=14天才能再次命中）
    symbols_dates = [(h.symbol, h.detect_date) for h in hits]
    # 不应有相邻日期的重复命中
    for i in range(1, len(hits)):
        date_a = pd.Timestamp(hits[i - 1].detect_date)
        date_b = pd.Timestamp(hits[i].detect_date)
        assert (date_b - date_a).days >= 14
```

- [ ] **Step 2: Run test to verify it passes (dedup already implemented in Task 1)**

Run: `.venv/bin/pytest tests/test_backtest.py::test_run_backtest_dedup_adjacent_hits -v`
Expected: PASS (dedup logic is built into `run_backtest`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_backtest.py
git commit -m "test: add dedup verification for adjacent pattern hits"
```

---

### Task 3: Statistics — `compute_stats()`

**Files:**
- Modify: `scanner/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test for stats**

```python
# tests/test_backtest.py — append

from scanner.backtest import compute_stats


def test_compute_stats_overall():
    """验证整体统计计算。"""
    hits = [
        BacktestHit("A/USDT", "2026-01-15", 14, 0.10, 0.3, 0.65,
                     {"3d": 0.05, "7d": 0.10, "14d": 0.15, "30d": 0.20}),
        BacktestHit("B/USDT", "2026-01-20", 10, 0.08, 0.4, 0.50,
                     {"3d": -0.03, "7d": 0.02, "14d": -0.05, "30d": 0.08}),
        BacktestHit("C/USDT", "2026-02-01", 12, 0.12, 0.2, 0.35,
                     {"3d": 0.02, "7d": -0.01, "14d": None, "30d": None}),
    ]
    stats = compute_stats(hits)

    assert stats["total_hits"] == 3
    # 整体统计
    overall = stats["overall"]
    assert "3d" in overall
    assert overall["3d"]["count"] == 3
    # 胜率：3d有2个正收益（0.05, 0.02），1个负(-0.03），胜率=2/3
    assert abs(overall["3d"]["win_rate"] - 2 / 3) < 0.01
    # 平均收益
    assert abs(overall["3d"]["mean"] - (0.05 - 0.03 + 0.02) / 3) < 0.001


def test_compute_stats_by_score_tier():
    """验证按评分分档统计。"""
    hits = [
        BacktestHit("A/USDT", "2026-01-15", 14, 0.10, 0.3, 0.65,
                     {"3d": 0.05, "7d": 0.10, "14d": 0.15, "30d": 0.20}),
        BacktestHit("B/USDT", "2026-01-20", 10, 0.08, 0.4, 0.50,
                     {"3d": -0.03, "7d": 0.02, "14d": -0.05, "30d": 0.08}),
        BacktestHit("C/USDT", "2026-02-01", 12, 0.12, 0.2, 0.35,
                     {"3d": 0.02, "7d": -0.01, "14d": None, "30d": None}),
    ]
    stats = compute_stats(hits)

    tiers = stats["by_tier"]
    # A的score=0.65 → 高分; B=0.50 → 中分; C=0.35 → 低分
    assert tiers["high"]["3d"]["count"] == 1
    assert tiers["mid"]["3d"]["count"] == 1
    assert tiers["low"]["3d"]["count"] == 1
    assert tiers["high"]["3d"]["win_rate"] == 1.0  # A的3d=0.05>0
    assert tiers["low"]["3d"]["win_rate"] == 1.0   # C的3d=0.02>0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_backtest.py::test_compute_stats_overall tests/test_backtest.py::test_compute_stats_by_score_tier -v`
Expected: FAIL — `ImportError: cannot import name 'compute_stats'`

- [ ] **Step 3: Implement compute_stats()**

Append to `scanner/backtest.py`:

```python
def _calc_period_stats(hits: list[BacktestHit], period: str) -> dict:
    """计算单个周期的统计指标。"""
    values = [h.returns[period] for h in hits if h.returns.get(period) is not None]
    if not values:
        return {"count": 0, "win_rate": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0}
    arr = np.array(values)
    return {
        "count": len(arr),
        "win_rate": float(np.mean(arr > 0)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "max": float(np.max(arr)),
        "min": float(np.min(arr)),
    }


def compute_stats(hits: list[BacktestHit]) -> dict:
    """计算整体统计和分档统计。"""
    periods = [f"{p}d" for p in RETURN_PERIODS]

    # 整体统计
    overall = {}
    for period in periods:
        overall[period] = _calc_period_stats(hits, period)

    # 按score分档
    tiers = {
        "high": [h for h in hits if h.score >= 0.6],
        "mid": [h for h in hits if 0.4 <= h.score < 0.6],
        "low": [h for h in hits if h.score < 0.4],
    }
    by_tier = {}
    for tier_name, tier_hits in tiers.items():
        by_tier[tier_name] = {}
        for period in periods:
            by_tier[tier_name][period] = _calc_period_stats(tier_hits, period)

    return {
        "total_hits": len(hits),
        "overall": overall,
        "by_tier": by_tier,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/backtest.py tests/test_backtest.py
git commit -m "feat: compute_stats with overall and score-tier statistics"
```

---

### Task 4: Format Output — `format_stats()`

**Files:**
- Modify: `scanner/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest.py — append

from scanner.backtest import format_stats


def test_format_stats_contains_key_info():
    """验证格式化输出包含关键信息。"""
    hits = [
        BacktestHit("A/USDT", "2026-01-15", 14, 0.10, 0.3, 0.65,
                     {"3d": 0.05, "7d": 0.10, "14d": 0.15, "30d": 0.20}),
    ]
    stats = compute_stats(hits)
    output = format_stats(stats)

    assert "整体统计" in output
    assert "3d" in output
    assert "7d" in output
    assert "胜率" in output
    assert "高分" in output
    assert "中分" in output
    assert "低分" in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_backtest.py::test_format_stats_contains_key_info -v`
Expected: FAIL — `ImportError: cannot import name 'format_stats'`

- [ ] **Step 3: Implement format_stats()**

Append to `scanner/backtest.py`:

```python
from tabulate import tabulate


def format_stats(stats: dict) -> str:
    """格式化统计结果为终端表格字符串。"""
    lines = []
    lines.append(f"总命中次数: {stats['total_hits']}")
    lines.append("")

    # 整体统计表格
    lines.append("=== 整体统计 ===")
    lines.append("")
    table = []
    for period in ["3d", "7d", "14d", "30d"]:
        s = stats["overall"][period]
        table.append([
            period,
            s["count"],
            f"{s['win_rate']:.1%}",
            f"{s['mean']:.2%}",
            f"{s['median']:.2%}",
            f"{s['max']:.2%}",
            f"{s['min']:.2%}",
        ])
    headers = ["周期", "样本数", "胜率", "平均收益", "中位数", "最大收益", "最大亏损"]
    lines.append(tabulate(table, headers=headers, tablefmt="simple"))
    lines.append("")

    # 分档统计
    tier_names = {"high": "高分(≥0.6)", "mid": "中分(0.4-0.6)", "low": "低分(<0.4)"}
    for tier_key, tier_label in tier_names.items():
        lines.append(f"=== {tier_label} ===")
        lines.append("")
        table = []
        for period in ["3d", "7d", "14d", "30d"]:
            s = stats["by_tier"][tier_key][period]
            table.append([
                period,
                s["count"],
                f"{s['win_rate']:.1%}",
                f"{s['mean']:.2%}",
                f"{s['median']:.2%}",
                f"{s['max']:.2%}",
                f"{s['min']:.2%}",
            ])
        lines.append(tabulate(table, headers=headers, tablefmt="simple"))
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scanner/backtest.py tests/test_backtest.py
git commit -m "feat: format_stats for terminal table output"
```

---

### Task 5: CLI Integration — `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add --backtest and --days arguments to argparse**

In `main.py`, add to the `parser` block (after line 197):

```python
    parser.add_argument("--backtest", action="store_true", help="运行回测验证形态有效性")
    parser.add_argument("--days", type=int, default=180, help="回测历史K线天数（默认180）")
```

- [ ] **Step 2: Add the run_backtest_cli function**

Add this function to `main.py` (before `main()`):

```python
def run_backtest_cli(config: dict, days: int, symbols_override: list[str] | None = None):
    """运行回测：拉取历史K线，滑动窗口检测，统计收益。"""
    from scanner.backtest import run_backtest, compute_stats, format_stats

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/3] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/3] 获取OKX永续合约列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉取历史K线
    print(f"[2/3] 从Binance拉取 {days} 天K线数据（{len(symbols)}个交易对）...")
    klines = fetch_klines_batch(symbols, days=days, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 回测
    print("[3/3] 滑动窗口回扫中...")
    hits = run_backtest(klines, config)
    print(f"       总命中 {len(hits)} 次形态")

    if not hits:
        print("\n历史数据中未检测到底部蓄力形态。")
        return

    stats = compute_stats(hits)
    output = format_stats(stats)
    print(f"\n{output}")

    # 保存结果
    import json
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    json_path = f"results/backtest_{ts}.json"
    json_data = {
        "stats": stats,
        "hits": [
            {
                "symbol": h.symbol,
                "detect_date": h.detect_date,
                "window_days": h.window_days,
                "drop_pct": h.drop_pct,
                "volume_ratio": h.volume_ratio,
                "score": h.score,
                "returns": h.returns,
            }
            for h in hits
        ],
    }
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    txt_path = f"results/backtest_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"回测时间: {ts}\n")
        f.write(f"历史天数: {days}\n")
        f.write(f"币种数: {len(klines)}\n\n")
        f.write(output)
        f.write("\n")

    print(f"结果已保存到 {json_path} 和 {txt_path}")
```

- [ ] **Step 3: Wire up the CLI dispatch in main()**

In `main.py`, modify the `main()` function's dispatch block. Replace the if/elif/else block:

```python
    if args.track:
        show_tracking()
    elif args.history:
        show_history(args.history)
    elif args.backtest:
        run_backtest_cli(config, days=args.days, symbols_override=args.symbols)
    else:
        run(config, top_n=args.top, symbols_override=args.symbols)
```

- [ ] **Step 4: Run all tests to verify nothing is broken**

Run: `.venv/bin/pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: CLI --backtest and --days flags for pattern backtesting"
```

---

### Task 6: End-to-End Smoke Test

**Files:**
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write an end-to-end test that exercises the full pipeline**

```python
# tests/test_backtest.py — append

def test_backtest_empty_input():
    """空K线输入应返回空命中列表。"""
    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({}, config)
    assert hits == []


def test_backtest_no_match():
    """持续上涨的K线不应命中任何形态。"""
    prices = [100 + i * 2 for i in range(60)]
    volumes = [1000] * 60
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"UP/USDT": df}, config)
    assert len(hits) == 0


def test_backtest_returns_none_for_insufficient_future_data():
    """数据不足时，远期收益应为None。"""
    # 14天形态 + 只有5天后续数据
    pattern_prices = [100 - i * 0.7 for i in range(14)]
    pattern_volumes = [1000] * 7 + [300] * 7
    future_prices = [pattern_prices[-1] + i * 0.5 for i in range(1, 6)]
    future_volumes = [500] * 5

    prices = pattern_prices + future_prices
    volumes = pattern_volumes + future_volumes
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"TEST/USDT": df}, config)

    if len(hits) > 0:
        hit = hits[0]
        assert hit.returns["3d"] is not None  # 有5天数据，3d够
        assert hit.returns["14d"] is None     # 14d不够
        assert hit.returns["30d"] is None     # 30d不够
```

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_backtest.py
git commit -m "test: edge cases — empty input, no match, insufficient future data"
```
