# 支撑/阻力位入场 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在信号生成时优先用 Pivot 支撑/阻力位定入场、止损、止盈，找不到有效层级时退回现有评分折扣逻辑。

**Architecture:** 新增 `scanner/levels.py` 负责 Pivot 识别；`scanner/signal.py` 新增 `klines_map` 参数和 `_try_sr_entry()` 辅助函数；`main.py` 透传 `klines`，输出表格新增 `[SR]`/`[SD]` 标识。

**Tech Stack:** Python 3.13, pandas, pytest

---

## 文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `scanner/levels.py` | Pivot 检测：4 个公开函数 |
| 新建 | `tests/test_levels.py` | levels 单元测试 |
| 修改 | `scanner/signal.py` | 新增 `klines_map` 参数、`entry_method` 字段、`_try_sr_entry` |
| 修改 | `tests/test_signal.py` | 新增 SR 路径测试用例 |
| 修改 | `main.py` | 3 处 `generate_signals` 调用透传 `klines`，输出加标识 |

---

## Task 1: 实现 `scanner/levels.py`（TDD）

**Files:**
- Create: `scanner/levels.py`
- Create: `tests/test_levels.py`

---

- [ ] **Step 1: 写第一批失败测试（数据不足 & 空列表）**

新建 `tests/test_levels.py`：

```python
import pandas as pd
import pytest
from scanner.levels import find_pivot_lows, find_pivot_highs, nearest_support, nearest_resistance


def _make_df(lows: list[float], highs: list[float] | None = None) -> pd.DataFrame:
    if highs is None:
        highs = [l + 5.0 for l in lows]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [1000.0] * len(lows),
    })


def test_pivot_lows_insufficient_data():
    """数据不足 left+right+1=11 行时返回空列表，不抛异常。"""
    df = _make_df([100.0] * 10)
    assert find_pivot_lows(df, left=5, right=5) == []


def test_pivot_highs_insufficient_data():
    df = _make_df([100.0] * 10)
    assert find_pivot_highs(df, left=5, right=5) == []
```

- [ ] **Step 2: 运行，确认失败（ImportError 即可）**

```bash
.venv/bin/pytest tests/test_levels.py -v
```

期望：`ImportError: cannot import name 'find_pivot_lows'`

---

- [ ] **Step 3: 创建 `scanner/levels.py` 骨架**

```python
import pandas as pd


def find_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 支撑位价格列表（升序）。
    判定：lows[i] 严格小于左 left 根和右 right 根的最小值。
    数据不足时返回空列表。
    """
    if len(df) < left + right + 1:
        return []
    lows = df["low"].values.astype(float)
    pivots = []
    for i in range(left, len(lows) - right):
        left_min = float(min(lows[i - left:i]))
        right_min = float(min(lows[i + 1:i + right + 1]))
        if lows[i] < left_min and lows[i] < right_min:
            pivots.append(float(lows[i]))
    return sorted(set(pivots))


def find_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 阻力位价格列表（升序）。"""
    if len(df) < left + right + 1:
        return []
    highs = df["high"].values.astype(float)
    pivots = []
    for i in range(left, len(highs) - right):
        left_max = float(max(highs[i - left:i]))
        right_max = float(max(highs[i + 1:i + right + 1]))
        if highs[i] > left_max and highs[i] > right_max:
            pivots.append(float(highs[i]))
    return sorted(set(pivots))


def nearest_support(
    df: pd.DataFrame, price: float, max_dist: float | None = None
) -> float | None:
    """返回低于 price 的最近支撑位。
    max_dist：(price - level) / price 的上限，None 表示不过滤。
    """
    levels = find_pivot_lows(df)
    candidates = [l for l in levels if l < price]
    if max_dist is not None:
        candidates = [l for l in candidates if (price - l) / price <= max_dist]
    return max(candidates) if candidates else None


def nearest_resistance(
    df: pd.DataFrame, price: float, max_dist: float | None = None
) -> float | None:
    """返回高于 price 的最近阻力位。
    max_dist：(level - price) / price 的上限，None 表示不过滤。
    """
    levels = find_pivot_highs(df)
    candidates = [l for l in levels if l > price]
    if max_dist is not None:
        candidates = [l for l in candidates if (l - price) / price <= max_dist]
    return min(candidates) if candidates else None
```

- [ ] **Step 4: 运行，确认通过**

```bash
.venv/bin/pytest tests/test_levels.py -v
```

期望：2 tests PASSED

---

- [ ] **Step 5: 补充 Pivot 识别核心测试**

在 `tests/test_levels.py` 追加：

```python
def test_find_pivot_lows_v_shape():
    """V 形 df：底部 index=10 应被识别为支撑位。"""
    # lows[i] = 80 + abs(i - 10) * 2，lows[10]=80 是最小值
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    result = find_pivot_lows(df, left=5, right=5)
    assert 80.0 in result


def test_find_pivot_highs_inverted_v():
    """倒 V 形 df：顶部 index=12 应被识别为阻力位。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    result = find_pivot_highs(df, left=5, right=5)
    assert 105.0 in result


def test_nearest_support_within_max_dist():
    """支撑在 max_dist 以内时能找到。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    # 当前价格约为 lows[15] = 90，支撑 80，(90-80)/90 ≈ 11% > 5%
    result = nearest_support(df, price=82.0, max_dist=0.05)
    # 82 * (1-0.05) = 77.9，支撑 80 在范围内 (82-80)/82 ≈ 2.4%
    assert result == 80.0


def test_nearest_support_outside_max_dist_returns_none():
    """支撑超出 max_dist 时返回 None。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    # price=100, support=80, dist=20% > 5%
    result = nearest_support(df, price=100.0, max_dist=0.05)
    assert result is None


def test_nearest_resistance_found():
    """阻力位在 price 上方时能找到。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    result = nearest_resistance(df, price=96.0)
    assert result == 105.0


def test_nearest_resistance_with_max_dist_filters():
    """阻力位超出 max_dist 时返回 None。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    # price=100, resistance=105, dist=5% == max_dist=0.05 → 应找到（≤）
    result = nearest_resistance(df, price=100.0, max_dist=0.05)
    assert result == 105.0
    # price=101, dist=(105-101)/101 ≈ 3.96% < 5% → 找到
    result2 = nearest_resistance(df, price=101.0, max_dist=0.03)
    # dist=3.96% > 3% → None
    assert result2 is None


def test_no_support_below_price():
    """价格低于所有 Pivot 低点时返回 None。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    result = nearest_support(df, price=70.0, max_dist=0.05)
    assert result is None
```

- [ ] **Step 6: 运行，确认通过**

```bash
.venv/bin/pytest tests/test_levels.py -v
```

期望：9 tests PASSED

---

- [ ] **Step 7: 提交**

```bash
git add scanner/levels.py tests/test_levels.py
git commit -m "feat: add pivot support/resistance detection (levels.py)"
```

---

## Task 2: 修改 `scanner/signal.py` — 支撑/阻力路径

**Files:**
- Modify: `scanner/signal.py`
- Modify: `tests/test_signal.py`

---

- [ ] **Step 1: 写失败测试（SR 路径）**

在 `tests/test_signal.py` 末尾追加：

```python
import numpy as np


def _make_sr_df(support: float, resistance: float, current_price: float) -> pd.DataFrame:
    """
    构造一个包含明确支撑/阻力位的 df（共 25 根 K 线）。
    - 第 10 根 K 线 low = support（V 形低点）
    - 第 5 根 K 线 high = resistance（倒 V 形高点）
    - 其余 K 线 close/high/low 围绕 current_price 分布
    """
    n = 25
    lows = [current_price * 0.99] * n
    highs = [current_price * 1.01] * n
    # Pivot low at index 10
    for i in range(n):
        dist = abs(i - 10)
        lows[i] = support + dist * (current_price - support) / 12.0
    lows[10] = support
    # Pivot high at index 5
    for i in range(n):
        dist = abs(i - 5)
        highs[i] = resistance - dist * (resistance - current_price) / 8.0
    highs[5] = resistance
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [1000.0] * n,
    })


def test_sr_path_used_when_levels_found():
    """有效支撑/阻力时走 SR 路径，entry_method='support_resistance'。"""
    price = 100.0
    support = 97.0    # (100-97)/100 = 3% < max_stop_loss=5%
    resistance = 108.0
    df = _make_sr_df(support, resistance, price)
    matches = [{"symbol": "A/USDT", "price": price, "score": 0.85,
                "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14}]
    config = SignalConfig(min_score=0.8, max_stop_loss=0.05)
    signals = generate_signals(matches, config, klines_map={"A/USDT": df})
    assert len(signals) == 1
    s = signals[0]
    assert s.entry_method == "support_resistance"
    assert abs(s.entry_price - support * 1.005) < 0.01
    assert abs(s.take_profit_price - resistance * 0.995) < 0.01
    assert s.stop_loss_price < s.entry_price


def test_sr_path_falls_back_when_support_too_far():
    """支撑超出 max_stop_loss 时退回折扣逻辑。"""
    price = 100.0
    support = 93.0    # (100-93)/100 = 7% > max_stop_loss=5%
    resistance = 110.0
    df = _make_sr_df(support, resistance, price)
    matches = [{"symbol": "B/USDT", "price": price, "score": 0.85,
                "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14}]
    config = SignalConfig(min_score=0.8, max_stop_loss=0.05)
    signals = generate_signals(matches, config, klines_map={"B/USDT": df})
    assert len(signals) == 1
    assert signals[0].entry_method == "score_discount"


def test_sr_path_falls_back_when_no_klines_map():
    """klines_map=None 时退回折扣逻辑。"""
    matches = [{"symbol": "C/USDT", "price": 100.0, "score": 0.85,
                "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14}]
    config = SignalConfig(min_score=0.8)
    signals = generate_signals(matches, config, klines_map=None)
    assert signals[0].entry_method == "score_discount"


def test_sr_path_falls_back_when_symbol_not_in_map():
    """symbol 不在 klines_map 时退回折扣逻辑。"""
    matches = [{"symbol": "D/USDT", "price": 100.0, "score": 0.85,
                "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14}]
    config = SignalConfig(min_score=0.8)
    signals = generate_signals(matches, config, klines_map={"OTHER/USDT": pd.DataFrame()})
    assert signals[0].entry_method == "score_discount"


def test_existing_tests_unaffected_without_klines_map():
    """不传 klines_map 时，已有行为完全不变（entry_method='score_discount'）。"""
    matches = [{"symbol": "X/USDT", "price": 100.0, "score": 0.70,
                "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14}]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)
    s = signals[0]
    assert abs(s.entry_price - 97.5) < 0.01
    assert s.entry_method == "score_discount"
```

- [ ] **Step 2: 运行，确认失败（generate_signals 不接受 klines_map 参数）**

```bash
.venv/bin/pytest tests/test_signal.py -v -k "sr_path or unaffected"
```

期望：5 tests FAIL（TypeError 或 AttributeError）

---

- [ ] **Step 3: 修改 `scanner/signal.py`**

将文件内容替换为：

```python
import math
from dataclasses import dataclass, field

import pandas as pd

from scanner.levels import nearest_support, nearest_resistance


@dataclass
class SignalConfig:
    min_score: float = 0.84
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0
    atr_tp_multiplier: float = 3.0
    confirmation: bool = True
    confirmation_min_pass: int = 4
    max_stop_loss: float = 0.05


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """计算 ATR (Average True Range)。返回最后一根K线的ATR值。"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    return float(atr)


@dataclass
class TradeSignal:
    symbol: str
    price: float
    score: float
    drop_pct: float
    volume_ratio: float
    window_days: int
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    hold_days: int
    signal_type: str = ""
    mode: str = ""
    sl_capped: bool = False
    market_cap_m: float = 0.0
    entry_method: str = ""  # "support_resistance" | "score_discount"


def _entry_discount(score: float) -> float:
    """评分越高回撤越小，评分越低回撤越大。"""
    if score >= 0.9:
        return 0.01
    if score >= 0.8:
        return 0.02
    if score >= 0.7:
        return 0.025
    return 0.03


def _try_sr_entry(
    df: pd.DataFrame,
    price: float,
    is_bearish: bool,
    atr: float,
    use_atr: bool,
    config: "SignalConfig",
) -> "tuple[float, float, float, bool] | None":
    """尝试支撑/阻力路径。返回 (entry, sl_price, tp_price, sl_capped) 或 None（降级）。"""
    if is_bearish:
        resistance = nearest_resistance(df, price, max_dist=config.max_stop_loss)
        support = nearest_support(df, price) if resistance is not None else None
        if resistance is None or support is None or resistance <= support:
            return None
        entry = resistance * 0.995
        sl_raw = resistance + (atr if use_atr else resistance * config.stop_loss)
        tp_price = support * 1.005
    else:
        support = nearest_support(df, price, max_dist=config.max_stop_loss)
        resistance = nearest_resistance(df, price) if support is not None else None
        if support is None or resistance is None or resistance <= support:
            return None
        entry = support * 1.005
        sl_raw = support - (atr if use_atr else support * config.stop_loss)
        tp_price = resistance * 0.995

    sl_capped = False
    sl_dist = abs(sl_raw - entry) / entry
    if sl_dist > config.max_stop_loss:
        sl_price = entry * (1 + config.max_stop_loss) if is_bearish else entry * (1 - config.max_stop_loss)
        sl_capped = True
    else:
        sl_price = sl_raw

    return entry, sl_price, tp_price, sl_capped


def generate_signals(
    matches: list[dict],
    signal_config: SignalConfig,
    klines_map: dict[str, pd.DataFrame] | None = None,
) -> list[TradeSignal]:
    """过滤低分结果，为通过的结果生成交易建议。
    klines_map：symbol -> df，传入时优先走支撑/阻力路径。
    """
    signals = []
    for m in matches:
        if m["score"] < signal_config.min_score:
            continue
        price = m["price"]
        score = m["score"]
        signal_type = m.get("signal_type", "")
        is_bearish = signal_type == "顶背离"

        atr = m.get("atr", 0)
        use_atr = atr > 0 and not math.isnan(atr)

        # 支撑/阻力路径（优先）
        entry_method = "score_discount"
        sl_capped = False
        df = klines_map.get(m["symbol"]) if klines_map else None
        if df is not None:
            sr = _try_sr_entry(df, price, is_bearish, atr, use_atr, signal_config)
            if sr is not None:
                entry, sl_price, tp_price, sl_capped = sr
                entry_method = "support_resistance"
                signals.append(TradeSignal(
                    symbol=m["symbol"],
                    price=price,
                    score=score,
                    drop_pct=m.get("drop_pct", 0),
                    volume_ratio=m.get("volume_ratio", 0),
                    window_days=m.get("window_days", 0),
                    entry_price=entry,
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price,
                    hold_days=signal_config.hold_days,
                    signal_type=signal_type,
                    mode=m.get("mode", ""),
                    sl_capped=sl_capped,
                    market_cap_m=m.get("market_cap_m", 0.0),
                    entry_method=entry_method,
                ))
                continue

        # 原有折扣逻辑（兜底）
        discount = _entry_discount(score)
        if is_bearish:
            entry = price * (1 + discount)
            if use_atr:
                sl_price = entry + signal_config.atr_sl_multiplier * atr
                tp_price = entry - signal_config.atr_tp_multiplier * atr
            else:
                sl_price = entry * (1 + signal_config.stop_loss)
                tp_price = entry * (1 - signal_config.take_profit)
        else:
            entry = price * (1 - discount)
            if use_atr:
                sl_price = entry - signal_config.atr_sl_multiplier * atr
                tp_price = entry + signal_config.atr_tp_multiplier * atr
            else:
                sl_price = entry * (1 - signal_config.stop_loss)
                tp_price = entry * (1 + signal_config.take_profit)

        if use_atr:
            sl_dist = abs(sl_price - entry) / entry
            if sl_dist > signal_config.max_stop_loss:
                sl_price = entry * (1 + signal_config.max_stop_loss) if is_bearish else entry * (1 - signal_config.max_stop_loss)
                sl_capped = True

        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=score,
            drop_pct=m.get("drop_pct", 0),
            volume_ratio=m.get("volume_ratio", 0),
            window_days=m.get("window_days", 0),
            entry_price=entry,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            hold_days=signal_config.hold_days,
            signal_type=signal_type,
            mode=m.get("mode", ""),
            sl_capped=sl_capped,
            market_cap_m=m.get("market_cap_m", 0.0),
            entry_method=entry_method,
        ))
    return signals
```

- [ ] **Step 4: 运行全部 signal 测试，确认通过**

```bash
.venv/bin/pytest tests/test_signal.py -v
```

期望：全部 PASSED（原有测试 + 新增 5 个）

---

- [ ] **Step 5: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v
```

期望：全部 PASSED

---

- [ ] **Step 6: 提交**

```bash
git add scanner/signal.py tests/test_signal.py
git commit -m "feat: add support/resistance entry path to generate_signals"
```

---

## Task 3: 修改 `main.py` — 透传 klines_map，输出加标识

**Files:**
- Modify: `main.py` (3 处 generate_signals 调用，3 处输出表格)

---

- [ ] **Step 1: 修改第一处（run() 函数，约第 228 行）**

找到：
```python
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

替换为：
```python
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

同一函数里输出表格部分，找到：
```python
        table_data.append([
            i,
            s.symbol,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
            f"{s.take_profit_price:.4f}",
            s.hold_days,
        ])
```

替换为：
```python
        entry_tag = " [SR]" if s.entry_method == "support_resistance" else " [SD]"
        table_data.append([
            i,
            s.symbol,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}" + entry_tag,
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
            f"{s.take_profit_price:.4f}",
            s.hold_days,
        ])
```

---

- [ ] **Step 2: 修改第二处（run_divergence() 函数，约第 387 行）**

找到：
```python
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

替换为：
```python
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

同函数输出表格（约第 407 行），与 Step 1 相同修改（添加 `entry_tag`）。

---

- [ ] **Step 3: 修改第三处（run_new_coin_observation() 函数，约第 554 行）**

找到：
```python
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

替换为：
```python
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")
```

同函数输出表格（约第 566 行），与 Step 1 相同修改。

---

- [ ] **Step 4: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v
```

期望：全部 PASSED

---

- [ ] **Step 5: 提交**

```bash
git add main.py
git commit -m "feat: pass klines_map to generate_signals, show SR/SD tag in output"
```

---

## 验收检查

- [ ] `tests/test_levels.py` 9 个测试全部通过
- [ ] `tests/test_signal.py` 原有 14 个 + 新增 5 个全部通过
- [ ] `entry_method` 字段在 SR 路径时为 `"support_resistance"`，兜底时为 `"score_discount"`
- [ ] 输出表格入场价列显示 `[SR]` 或 `[SD]` 标识
- [ ] 3 个扫描模式（run / run_divergence / run_new_coin_observation）全部透传 klines_map
