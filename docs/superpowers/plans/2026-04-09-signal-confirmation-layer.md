# 信号确认层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在信号生成前增加多指标共振 + 量价验证的确认层，过滤假信号，提升方向准确率。

**Architecture:** 新增 `scanner/confirmation.py` 作为后置过滤层，包含 RSI、OBV、涨跌日量比、MFI 四项指标检查。在 `main.py` 的 `run()` 和 `run_divergence()` 中，`generate_signals()` 之前调用确认层过滤候选信号。通过 config 和 CLI 参数可开关。

**Tech Stack:** Python 3.13, pandas, numpy（已有依赖，无新增）

---

### Task 1: 确认层核心模块 — 指标计算函数

**Files:**
- Create: `scanner/confirmation.py`
- Create: `tests/test_confirmation.py`

- [ ] **Step 1: 写 compute_rsi 的失败测试**

```python
# tests/test_confirmation.py
import pandas as pd
import numpy as np
from scanner.confirmation import compute_rsi


def test_compute_rsi_overbought():
    """连续上涨应产生高 RSI (>70)。"""
    prices = [10 + i * 0.5 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert rsi > 70


def test_compute_rsi_oversold():
    """连续下跌应产生低 RSI (<30)。"""
    prices = [30 - i * 0.5 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert rsi < 30


def test_compute_rsi_neutral():
    """震荡行情 RSI 应在 40-60 之间。"""
    prices = [10 + (i % 3 - 1) * 0.2 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert 30 <= rsi <= 70
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.confirmation'`

- [ ] **Step 3: 实现 compute_rsi**

```python
# scanner/confirmation.py
import numpy as np
import pandas as pd


def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    """计算 RSI(period)，返回最新值。"""
    deltas = closes.diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)
    avg_gain = gains.rolling(period).mean().iloc[-1]
    avg_loss = losses.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_rsi in confirmation module"
```

---

### Task 2: OBV 趋势计算

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写 compute_obv_trend 的失败测试**

```python
# tests/test_confirmation.py — 追加
from scanner.confirmation import compute_obv_trend


def test_obv_trend_positive():
    """上涨日多于下跌日时，近7日 OBV 变化应为正。"""
    closes = pd.Series([10, 11, 12, 11.5, 12.5, 13, 14, 13.5, 14.5, 15])
    volumes = pd.Series([100] * 10)
    trend = compute_obv_trend(closes, volumes, days=7)
    assert trend > 0


def test_obv_trend_negative():
    """下跌日多于上涨日时，近7日 OBV 变化应为负。"""
    closes = pd.Series([15, 14, 13, 13.5, 12.5, 12, 11, 11.5, 10.5, 10])
    volumes = pd.Series([100] * 10)
    trend = compute_obv_trend(closes, volumes, days=7)
    assert trend < 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_obv_trend_positive -v`
Expected: FAIL — `ImportError: cannot import name 'compute_obv_trend'`

- [ ] **Step 3: 实现 compute_obv_trend**

```python
# scanner/confirmation.py — 追加
def compute_obv_trend(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float:
    """计算近 days 日的 OBV 净变化。正=净流入，负=净流出。"""
    obv = pd.Series(0.0, index=closes.index)
    for i in range(1, len(closes)):
        if closes.iloc[i] > closes.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + volumes.iloc[i]
        elif closes.iloc[i] < closes.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - volumes.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]
    return float(obv.iloc[-1] - obv.iloc[-(days + 1)])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_obv_trend in confirmation module"
```

---

### Task 3: 涨跌日量比计算

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写 compute_up_down_volume_ratio 的失败测试**

```python
# tests/test_confirmation.py — 追加
from scanner.confirmation import compute_up_down_volume_ratio


def test_volume_ratio_bull_dominant():
    """上涨日放量、下跌日缩量，量比应 > 1.5。"""
    closes = pd.Series([10, 11, 10.5, 12, 11.8, 13, 12.5, 14])
    volumes = pd.Series([100, 500, 100, 500, 100, 500, 100, 500])
    ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    assert ratio > 1.5


def test_volume_ratio_bear_dominant():
    """下跌日放量、上涨日缩量，量比应 < 0.7。"""
    closes = pd.Series([14, 13, 13.5, 12, 12.2, 11, 11.5, 10])
    volumes = pd.Series([100, 500, 100, 500, 100, 500, 100, 500])
    ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    assert ratio < 0.7


def test_volume_ratio_no_down_days():
    """全部上涨日，量比应为 inf。"""
    closes = pd.Series([10, 11, 12, 13, 14])
    volumes = pd.Series([100] * 5)
    ratio = compute_up_down_volume_ratio(closes, volumes, days=4)
    assert ratio == float("inf")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_volume_ratio_bull_dominant -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 compute_up_down_volume_ratio**

```python
# scanner/confirmation.py — 追加
def compute_up_down_volume_ratio(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float:
    """计算近 days 日上涨日总成交量 / 下跌日总成交量。"""
    up_vol = 0.0
    down_vol = 0.0
    start = max(1, len(closes) - days)
    for i in range(start, len(closes)):
        if closes.iloc[i] >= closes.iloc[i - 1]:
            up_vol += volumes.iloc[i]
        else:
            down_vol += volumes.iloc[i]
    if down_vol == 0:
        return float("inf")
    return up_vol / down_vol
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_up_down_volume_ratio in confirmation module"
```

---

### Task 4: MFI 计算

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写 compute_mfi 的失败测试**

```python
# tests/test_confirmation.py — 追加
from scanner.confirmation import compute_mfi


def test_mfi_range():
    """MFI 应在 0-100 之间。"""
    n = 30
    highs = pd.Series([10 + i * 0.3 + 0.5 for i in range(n)])
    lows = pd.Series([10 + i * 0.3 - 0.5 for i in range(n)])
    closes = pd.Series([10 + i * 0.3 for i in range(n)])
    volumes = pd.Series([1000] * n)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    assert 0 <= mfi <= 100


def test_mfi_high_on_rally():
    """持续上涨+放量时 MFI 应偏高 (>50)。"""
    n = 30
    highs = pd.Series([10 + i * 0.5 + 0.2 for i in range(n)])
    lows = pd.Series([10 + i * 0.5 - 0.1 for i in range(n)])
    closes = pd.Series([10 + i * 0.5 for i in range(n)])
    volumes = pd.Series([1000 + i * 100 for i in range(n)])
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    assert mfi > 50
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_mfi_range -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 compute_mfi**

```python
# scanner/confirmation.py — 追加
def compute_mfi(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    volumes: pd.Series,
    period: int = 14,
) -> float:
    """计算 MFI(period)，返回最新值。"""
    typical_price = (highs + lows + closes) / 3.0
    raw_mf = typical_price * volumes
    pos_mf = pd.Series(0.0, index=closes.index)
    neg_mf = pd.Series(0.0, index=closes.index)
    for i in range(1, len(typical_price)):
        if typical_price.iloc[i] > typical_price.iloc[i - 1]:
            pos_mf.iloc[i] = raw_mf.iloc[i]
        else:
            neg_mf.iloc[i] = raw_mf.iloc[i]
    pos_sum = pos_mf.rolling(period).sum().iloc[-1]
    neg_sum = neg_mf.rolling(period).sum().iloc[-1]
    if neg_sum == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + pos_sum / neg_sum))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_mfi in confirmation module"
```

---

### Task 5: confirm_signal 主函数

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写 confirm_signal 的失败测试**

```python
# tests/test_confirmation.py — 追加
from scanner.confirmation import confirm_signal, ConfirmationResult


def _make_df(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造含 OHLCV 的 DataFrame。"""
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


def test_confirm_long_all_pass():
    """健康的底部反弹：RSI 适中、OBV 流入、多头量比、MFI 正常 → 4/4 通过。"""
    # 先跌后涨，上涨日放量
    prices = [20 - i * 0.3 for i in range(20)] + [14 + i * 0.4 for i in range(10)]
    vols = [100] * 20 + [500] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=3)
    assert result.passed is True
    assert result.passed_count >= 3


def test_confirm_long_fail_obv_and_volume():
    """价格见底但下跌日放量（类似 VIC）→ OBV 和量比不过 → 过滤。"""
    # 下跌放量，小幅反弹缩量
    prices = [20 - i * 0.4 for i in range(20)] + [12, 12.1, 11.9, 12.2, 12, 12.3, 11.8, 12.1, 11.9, 12]
    vols = [500] * 20 + [50] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=3)
    assert result.passed is False
    assert result.obv_ok is False


def test_confirm_short_pass():
    """顶部反转：OBV 流出、空头量比 → 做空确认通过。"""
    prices = [10 + i * 0.3 for i in range(20)] + [16 - i * 0.4 for i in range(10)]
    vols = [100] * 20 + [500] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "short", min_pass=3)
    assert result.passed is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_confirm_long_all_pass -v`
Expected: FAIL — `ImportError: cannot import name 'confirm_signal'`

- [ ] **Step 3: 实现 confirm_signal 和 ConfirmationResult**

```python
# scanner/confirmation.py — 在文件顶部追加 dataclass import，然后追加以下内容

from dataclasses import dataclass


@dataclass
class ConfirmationResult:
    """信号确认结果。"""
    passed: bool
    rsi_ok: bool
    obv_ok: bool
    volume_ratio_ok: bool
    mfi_ok: bool
    passed_count: int
    details: dict


def confirm_signal(
    df: pd.DataFrame,
    direction: str,
    min_pass: int = 3,
) -> ConfirmationResult:
    """对候选信号做多指标确认。

    Args:
        df: K线 DataFrame (需含 open/high/low/close/volume)
        direction: "long" 或 "short"
        min_pass: 4项检查中至少通过几项才算确认通过

    Returns:
        ConfirmationResult
    """
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    rsi = compute_rsi(closes, period=14)
    obv_trend = compute_obv_trend(closes, volumes, days=7)
    vol_ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)

    if direction == "long":
        rsi_ok = 30 <= rsi <= 70
        obv_ok = obv_trend > 0
        volume_ratio_ok = vol_ratio >= 1.0
        mfi_ok = 20 <= mfi <= 80
    else:
        rsi_ok = 30 <= rsi <= 70
        obv_ok = obv_trend < 0
        volume_ratio_ok = vol_ratio <= 1.0
        mfi_ok = 20 <= mfi <= 80

    checks = [rsi_ok, obv_ok, volume_ratio_ok, mfi_ok]
    passed_count = sum(checks)

    return ConfirmationResult(
        passed=passed_count >= min_pass,
        rsi_ok=rsi_ok,
        obv_ok=obv_ok,
        volume_ratio_ok=volume_ratio_ok,
        mfi_ok=mfi_ok,
        passed_count=passed_count,
        details={
            "rsi": round(rsi, 1),
            "obv_7d": round(obv_trend, 2),
            "up_down_vol_ratio": round(vol_ratio, 2),
            "mfi": round(mfi, 1),
        },
    )
```

注意：`from dataclasses import dataclass` 和 `ConfirmationResult` 需放在文件顶部（在 `import numpy` 之后），4 个 compute 函数之前。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 13 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add confirm_signal main function with ConfirmationResult"
```

---

### Task 6: config.yaml 和 SignalConfig 扩展

**Files:**
- Modify: `config.yaml`
- Modify: `scanner/signal.py`
- Modify: `main.py:20-42` (load_config)

- [ ] **Step 1: 在 config.yaml 的 signal 段新增两个字段**

在 `config.yaml` 的 `signal:` 段末尾追加：

```yaml
signal:
  min_score: 0.6
  hold_days: 3
  stop_loss: 0.05
  take_profit: 0.08
  confirmation: true              # 是否启用确认层
  confirmation_min_pass: 3        # 4项中至少通过几项
```

- [ ] **Step 2: 扩展 SignalConfig 数据类**

在 `scanner/signal.py` 的 `SignalConfig` 中追加两个字段：

```python
@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08
    confirmation: bool = True
    confirmation_min_pass: int = 3
```

- [ ] **Step 3: 更新 load_config 解析新字段**

在 `main.py` 的 `load_config()` 中，`SignalConfig` 构造处追加两行：

```python
    signal_config = SignalConfig(
        min_score=sig.get("min_score", 0.6),
        hold_days=sig.get("hold_days", 3),
        stop_loss=sig.get("stop_loss", 0.05),
        take_profit=sig.get("take_profit", 0.08),
        confirmation=sig.get("confirmation", True),
        confirmation_min_pass=sig.get("confirmation_min_pass", 3),
    )
```

- [ ] **Step 4: 运行全量测试确认不破坏现有功能**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过（新字段有默认值，不影响已有测试）

- [ ] **Step 5: 提交**

```bash
git add config.yaml scanner/signal.py main.py
git commit -m "feat: add confirmation config fields to SignalConfig and config.yaml"
```

---

### Task 7: main.py 集成确认层 — run() 和 run_divergence()

**Files:**
- Modify: `main.py:1-15` (imports)
- Modify: `main.py:126-134` (run 函数信号过滤前)
- Modify: `main.py:259-267` (run_divergence 函数信号过滤前)
- Modify: `main.py:562-592` (argparse 新增 --no-confirm)

- [ ] **Step 1: 添加 import**

在 `main.py` 顶部 imports 中追加：

```python
from scanner.confirmation import confirm_signal
```

- [ ] **Step 2: 在 run() 中插入确认过滤**

在 `main.py` 的 `run()` 函数中，`ranked = rank_results(...)` 之后、`signals = generate_signals(...)` 之前插入：

```python
    # 确认层过滤
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return
```

- [ ] **Step 3: 在 run_divergence() 中插入确认过滤**

在 `main.py` 的 `run_divergence()` 函数中，`ranked = rank_results(...)` 之后、`signals = generate_signals(...)` 之前插入：

```python
    # 确认层过滤
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            direction = "short" if m.get("signal_type") == "顶背离" else "long"
            result = confirm_signal(klines[m["symbol"]], direction, signal_config.confirmation_min_pass)
            if result.passed:
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return
```

- [ ] **Step 4: 添加 --no-confirm CLI 参数**

在 `main.py` 的 `main()` 函数中，argparse 部分追加：

```python
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="关闭信号确认层（多指标共振过滤）",
    )
```

在 `config, signal_config, ...= load_config(args.config)` 之后追加：

```python
    if args.no_confirm:
        signal_config = replace(signal_config, confirmation=False)
```

同时确保 `main.py` 顶部已有 `from dataclasses import replace` （已存在于 `run_new_coin_observation` 的 imports 中，检查是否在文件顶部）。

- [ ] **Step 5: 运行全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add main.py
git commit -m "feat: integrate confirmation layer into run() and run_divergence()"
```

---

### Task 8: backtest.py 支持确认层对比

**Files:**
- Modify: `scanner/backtest.py:25-89` (run_backtest)
- Modify: `tests/test_backtest.py`

- [ ] **Step 1: 写回测确认层的测试**

```python
# tests/test_backtest.py — 追加
def test_run_backtest_with_confirmation():
    """开启确认层后，命中数应 <= 无确认层的命中数。"""
    n_pattern = 14
    n_future = 30
    pattern_prices = [100 - i * 0.7 for i in range(n_pattern)]
    pattern_volumes = [1000] * 7 + [300] * 7
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
    hits_no_confirm = run_backtest({"TEST/USDT": df}, config, confirmation=False)
    hits_with_confirm = run_backtest({"TEST/USDT": df}, config, confirmation=True)
    assert len(hits_with_confirm) <= len(hits_no_confirm)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_backtest.py::test_run_backtest_with_confirmation -v`
Expected: FAIL — `TypeError: run_backtest() got an unexpected keyword argument 'confirmation'`

- [ ] **Step 3: 在 run_backtest 中添加 confirmation 参数**

修改 `scanner/backtest.py` 中 `run_backtest` 的签名和逻辑：

```python
from scanner.confirmation import confirm_signal

def run_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
    confirmation: bool = False,
    confirmation_min_pass: int = 3,
) -> list[BacktestHit]:
```

在 `if not result.matched: continue` 之后、`last_hit_idx = i` 之前追加：

```python
            # 确认层过滤
            if confirmation:
                conf = confirm_signal(slice_df, "long", confirmation_min_pass)
                if not conf.passed:
                    continue
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add scanner/backtest.py tests/test_backtest.py
git commit -m "feat: add confirmation support to run_backtest for A/B comparison"
```

---

### Task 9: 端到端验证

**Files:**
- 无新增文件

- [ ] **Step 1: 跑背离模式，确认确认层生效**

Run: `.venv/bin/python main.py --mode divergence`
Expected: 输出中出现 `[确认]` 行，如 `[确认] 20 -> 14 个 (过滤: VIC/USDT, ...)`

- [ ] **Step 2: 跑背离模式关闭确认层，确认可以关闭**

Run: `.venv/bin/python main.py --mode divergence --no-confirm`
Expected: 输出中不出现 `[确认]` 行，信号数量与之前一致（20 个）

- [ ] **Step 3: 跑蓄力模式，确认确认层生效**

Run: `.venv/bin/python main.py --mode accumulation`
Expected: 正常输出，如有命中会经过确认层

- [ ] **Step 4: 跑回测对比**

Run: `.venv/bin/python main.py --backtest --days 180`
Expected: 正常输出回测统计

- [ ] **Step 5: 全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 6: 提交（如有修复）**

如果端到端测试发现问题并修复了代码，提交修复。
