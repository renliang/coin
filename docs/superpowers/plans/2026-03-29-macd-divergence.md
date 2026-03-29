# MACD背离扫描模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--mode divergence` scanning mode that detects daily MACD bullish/bearish divergences across all OKX perpetual futures symbols.

**Architecture:** New `scanner/divergence.py` handles MACD calculation, pivot detection, and divergence scoring. `scanner/signal.py` gains a `signal_type` field to distinguish bullish/bearish. `main.py` adds `--mode` CLI arg routing to a new `run_divergence()` flow. DB gets a `mode` column.

**Tech Stack:** Python 3.13, pandas, numpy, ccxt (existing), tabulate (existing)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scanner/divergence.py` | Create | MACD calculation, pivot finding, divergence detection, scoring |
| `tests/test_divergence.py` | Create | Unit tests for all divergence detection logic |
| `scanner/signal.py` | Modify | Add `signal_type`/`mode` to TradeSignal, support bearish signals |
| `tests/test_signal.py` | Modify | Add tests for bearish signal generation |
| `scanner/tracker.py` | Modify | Add `mode` column to scan_results table |
| `main.py` | Modify | Add `--mode` arg, `run_divergence()` function |

---

### Task 1: MACD Calculation and Pivot Detection

**Files:**
- Create: `scanner/divergence.py`
- Create: `tests/test_divergence.py`

- [ ] **Step 1: Write failing tests for MACD calculation**

```python
# tests/test_divergence.py
import numpy as np
import pandas as pd
from scanner.divergence import compute_macd, find_pivots, detect_divergence, DivergenceResult


def _make_klines(closes: list[float], n: int | None = None) -> pd.DataFrame:
    if n is None:
        n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })


class TestComputeMACD:
    def test_returns_three_series(self):
        closes = pd.Series([float(100 + i) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        assert len(dif) == len(closes)
        assert len(dea) == len(closes)
        assert len(hist) == len(closes)

    def test_dif_positive_in_uptrend(self):
        closes = pd.Series([float(100 + i * 2) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        # After warmup period, DIF should be positive in uptrend
        assert dif.iloc[-1] > 0

    def test_dif_negative_in_downtrend(self):
        closes = pd.Series([float(200 - i * 2) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        assert dif.iloc[-1] < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_divergence.py::TestComputeMACD -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.divergence'`

- [ ] **Step 3: Implement compute_macd**

```python
# scanner/divergence.py
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DivergenceResult:
    """背离检测结果"""
    divergence_type: str    # "bullish" | "bearish" | "none"
    price_1: float          # 第一个极值点价格
    price_2: float          # 第二个极值点价格
    dif_1: float            # 第一个极值点DIF值
    dif_2: float            # 第二个极值点DIF值
    pivot_distance: int     # 两极值点间距（K线根数）
    score: float            # 综合评分 [0, 1]


def compute_macd(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD指标，返回 (DIF, DEA, MACD柱)。"""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_divergence.py::TestComputeMACD -v`
Expected: 3 passed

- [ ] **Step 5: Write failing tests for pivot detection**

Append to `tests/test_divergence.py`:

```python
class TestFindPivots:
    def test_finds_valley(self):
        # V-shape: a clear valley at index 5
        closes = [100, 98, 96, 94, 92, 90, 92, 94, 96, 98, 100,
                  98, 96, 94, 92, 90, 92, 94, 96, 98, 100]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert 5 in lows
        assert 15 in lows

    def test_finds_peak(self):
        # Inverted V: a clear peak at index 5
        closes = [90, 92, 94, 96, 98, 100, 98, 96, 94, 92, 90,
                  92, 94, 96, 98, 100, 98, 96, 94, 92, 90]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert 5 in highs
        assert 15 in highs

    def test_no_pivots_in_monotonic(self):
        closes = [float(100 + i) for i in range(20)]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert len(lows) == 0
        assert len(highs) == 0
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_divergence.py::TestFindPivots -v`
Expected: FAIL — `ImportError: cannot import name 'find_pivots'`

- [ ] **Step 7: Implement find_pivots**

Append to `scanner/divergence.py`:

```python
def find_pivots(
    series: pd.Series,
    pivot_len: int = 3,
) -> tuple[list[int], list[int]]:
    """找局部波谷和波峰的索引。

    波谷：某点比前后各 pivot_len 个点都低。
    波峰：某点比前后各 pivot_len 个点都高。
    """
    values = series.values.astype(float)
    n = len(values)
    lows = []
    highs = []
    for i in range(pivot_len, n - pivot_len):
        window = values[i - pivot_len: i + pivot_len + 1]
        if values[i] == np.min(window):
            lows.append(i)
        if values[i] == np.max(window):
            highs.append(i)
    return lows, highs
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_divergence.py -v`
Expected: 6 passed

- [ ] **Step 9: Commit**

```bash
git add scanner/divergence.py tests/test_divergence.py
git commit -m "feat: MACD calculation and pivot detection"
```

---

### Task 2: Divergence Detection and Scoring

**Files:**
- Modify: `scanner/divergence.py`
- Modify: `tests/test_divergence.py`

- [ ] **Step 1: Write failing tests for bullish divergence detection**

Append to `tests/test_divergence.py`:

```python
class TestDetectDivergence:
    def _make_bullish_divergence_data(self) -> pd.DataFrame:
        """构造底背离数据：价格创新低，但DIF未创新低。

        第一个波谷在 ~index 30，第二个在 ~index 55。
        价格在第二个波谷更低，但由于整体跌幅放缓，DIF第二次更高。
        """
        n = 70
        closes = []
        for i in range(n):
            if i < 30:
                # 急跌到波谷1
                closes.append(100 - i * 1.5)
            elif i < 40:
                # 反弹
                closes.append(55 + (i - 30) * 2.0)
            elif i < 55:
                # 缓跌到波谷2（价格更低，但跌速更慢 → DIF更高）
                closes.append(75 - (i - 40) * 1.8)
            else:
                # 小幅回升
                closes.append(48 + (i - 55) * 0.5)
        return _make_klines(closes, n)

    def test_bullish_divergence_detected(self):
        df = self._make_bullish_divergence_data()
        result = detect_divergence(df)
        assert result.divergence_type == "bullish"
        assert result.score > 0

    def _make_bearish_divergence_data(self) -> pd.DataFrame:
        """构造顶背离数据：价格创新高，但DIF未创新高。"""
        n = 70
        closes = []
        for i in range(n):
            if i < 30:
                # 急涨到波峰1
                closes.append(50 + i * 1.5)
            elif i < 40:
                # 回落
                closes.append(95 - (i - 30) * 2.0)
            elif i < 55:
                # 缓涨到波峰2（价格更高，但涨速更慢 → DIF更低）
                closes.append(75 + (i - 40) * 1.8)
            else:
                # 小幅回落
                closes.append(102 - (i - 55) * 0.5)
        return _make_klines(closes, n)

    def test_bearish_divergence_detected(self):
        df = self._make_bearish_divergence_data()
        result = detect_divergence(df)
        assert result.divergence_type == "bearish"
        assert result.score > 0

    def test_no_divergence_in_steady_uptrend(self):
        closes = [float(50 + i * 0.8) for i in range(70)]
        df = _make_klines(closes, 70)
        result = detect_divergence(df)
        assert result.divergence_type == "none"
        assert result.score == 0.0

    def test_insufficient_data_returns_none(self):
        closes = [100.0] * 20
        df = _make_klines(closes, 20)
        result = detect_divergence(df)
        assert result.divergence_type == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_divergence.py::TestDetectDivergence -v`
Expected: FAIL — `ImportError: cannot import name 'detect_divergence'`

- [ ] **Step 3: Implement detect_divergence and score_divergence**

Append to `scanner/divergence.py`:

```python
def _score_divergence(
    price_1: float,
    price_2: float,
    dif_1: float,
    dif_2: float,
    hist: pd.Series,
    idx_1: int,
    idx_2: int,
    div_type: str,
) -> float:
    """计算背离评分 [0, 1]。

    三个维度:
    - 背离强度 (权重0.4): 价格差与DIF差的偏离程度
    - MACD柱确认 (权重0.3): 第二极值点附近柱状图是否收缩
    - 时间合理性 (权重0.3): 间距越接近30天越好
    """
    # 1. 背离强度: 价格变化率与DIF变化率方向相反的程度
    price_change = abs(price_2 - price_1) / abs(price_1) if price_1 != 0 else 0
    dif_change = abs(dif_2 - dif_1) / (abs(dif_1) + 1e-10)
    strength = min(1.0, (price_change + dif_change) / 0.3)

    # 2. MACD柱确认: 第二极值点附近的柱值是否在回归零轴
    window = 5
    start = max(0, idx_2 - window)
    end = min(len(hist), idx_2 + window + 1)
    hist_slice = hist.iloc[start:end].values
    if div_type == "bullish":
        # 底背离: 柱值应从负回升(值变大)
        hist_trend = np.mean(np.diff(hist_slice)) if len(hist_slice) > 1 else 0
        confirm = min(1.0, max(0.0, hist_trend / (abs(hist.iloc[idx_1]) + 1e-10) * 10))
    else:
        # 顶背离: 柱值应从正回落(值变小)
        hist_trend = np.mean(np.diff(hist_slice)) if len(hist_slice) > 1 else 0
        confirm = min(1.0, max(0.0, -hist_trend / (abs(hist.iloc[idx_1]) + 1e-10) * 10))

    # 3. 时间合理性: 间距接近30天得分最高，线性衰减
    distance = idx_2 - idx_1
    time_score = max(0.0, 1.0 - abs(distance - 30) / 30)

    return strength * 0.4 + confirm * 0.3 + time_score * 0.3


def detect_divergence(
    df: pd.DataFrame,
    pivot_len: int = 3,
    min_distance: int = 15,
    max_distance: int = 60,
) -> DivergenceResult:
    """在日K线数据中检测MACD背离。

    需要至少40根K线(26根MACD预热 + 检测空间)。
    """
    none_result = DivergenceResult(
        divergence_type="none",
        price_1=0, price_2=0,
        dif_1=0, dif_2=0,
        pivot_distance=0,
        score=0.0,
    )

    if len(df) < 40:
        return none_result

    closes = df["close"].astype(float)
    dif, dea, hist = compute_macd(closes)

    # 在MACD预热期之后寻找极值点
    warmup = 26
    close_after = closes.iloc[warmup:]
    lows, highs = find_pivots(close_after, pivot_len=pivot_len)

    # 将索引调整回原始DataFrame
    lows = [i + warmup for i in lows]
    highs = [i + warmup for i in highs]

    best_result = none_result

    # 检查底背离: 遍历波谷对
    for i in range(len(lows) - 1):
        for j in range(i + 1, len(lows)):
            idx1, idx2 = lows[i], lows[j]
            dist = idx2 - idx1
            if dist < min_distance or dist > max_distance:
                continue
            p1, p2 = float(closes.iloc[idx1]), float(closes.iloc[idx2])
            d1, d2 = float(dif.iloc[idx1]), float(dif.iloc[idx2])
            # 底背离: 价格创新低，DIF未创新低
            if p2 < p1 and d2 > d1:
                score = _score_divergence(p1, p2, d1, d2, hist, idx1, idx2, "bullish")
                if score > best_result.score:
                    best_result = DivergenceResult(
                        divergence_type="bullish",
                        price_1=p1, price_2=p2,
                        dif_1=d1, dif_2=d2,
                        pivot_distance=dist,
                        score=score,
                    )

    # 检查顶背离: 遍历波峰对
    for i in range(len(highs) - 1):
        for j in range(i + 1, len(highs)):
            idx1, idx2 = highs[i], highs[j]
            dist = idx2 - idx1
            if dist < min_distance or dist > max_distance:
                continue
            p1, p2 = float(closes.iloc[idx1]), float(closes.iloc[idx2])
            d1, d2 = float(dif.iloc[idx1]), float(dif.iloc[idx2])
            # 顶背离: 价格创新高，DIF未创新高
            if p2 > p1 and d2 < d1:
                score = _score_divergence(p1, p2, d1, d2, hist, idx1, idx2, "bearish")
                if score > best_result.score:
                    best_result = DivergenceResult(
                        divergence_type="bearish",
                        price_1=p1, price_2=p2,
                        dif_1=d1, dif_2=d2,
                        pivot_distance=dist,
                        score=score,
                    )

    return best_result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_divergence.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/divergence.py tests/test_divergence.py
git commit -m "feat: divergence detection and scoring"
```

---

### Task 3: Extend TradeSignal for Divergence Mode

**Files:**
- Modify: `scanner/signal.py`
- Modify: `tests/test_signal.py`

- [ ] **Step 1: Write failing tests for bearish signal generation**

Append to `tests/test_signal.py`:

```python
def test_bearish_signal_reverses_sl_tp():
    """顶背离信号: 止损在上方, 止盈在下方。"""
    matches = [
        {
            "symbol": "X/USDT", "price": 100.0, "score": 0.70,
            "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
            "signal_type": "顶背离", "mode": "divergence",
        },
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == "顶背离"
    assert abs(s.stop_loss_price - 105.0) < 0.01   # 上方止损
    assert abs(s.take_profit_price - 92.0) < 0.01   # 下方止盈


def test_bullish_signal_default_direction():
    """底背离信号: 与原有做多方向一致。"""
    matches = [
        {
            "symbol": "Y/USDT", "price": 100.0, "score": 0.70,
            "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
            "signal_type": "底背离", "mode": "divergence",
        },
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == "底背离"
    assert abs(s.stop_loss_price - 95.0) < 0.01
    assert abs(s.take_profit_price - 108.0) < 0.01


def test_legacy_match_no_signal_type():
    """旧格式(无signal_type字段)仍正常工作。"""
    matches = [
        {"symbol": "A/USDT", "price": 100.0, "score": 0.65,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    signals = generate_signals(matches, SignalConfig(min_score=0.6))
    assert len(signals) == 1
    assert signals[0].signal_type == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_signal.py::test_bearish_signal_reverses_sl_tp tests/test_signal.py::test_bullish_signal_default_direction tests/test_signal.py::test_legacy_match_no_signal_type -v`
Expected: FAIL — `TradeSignal` has no `signal_type` field

- [ ] **Step 3: Update TradeSignal and generate_signals**

Replace the full content of `scanner/signal.py`:

```python
from dataclasses import dataclass


@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08


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


def generate_signals(
    matches: list[dict],
    signal_config: SignalConfig,
) -> list[TradeSignal]:
    """过滤低分结果，为通过的结果生成交易建议。"""
    signals = []
    for m in matches:
        if m["score"] < signal_config.min_score:
            continue
        price = m["price"]
        signal_type = m.get("signal_type", "")
        is_bearish = signal_type == "顶背离"

        if is_bearish:
            sl_price = price * (1 + signal_config.stop_loss)
            tp_price = price * (1 - signal_config.take_profit)
        else:
            sl_price = price * (1 - signal_config.stop_loss)
            tp_price = price * (1 + signal_config.take_profit)

        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=m["score"],
            drop_pct=m.get("drop_pct", 0),
            volume_ratio=m.get("volume_ratio", 0),
            window_days=m.get("window_days", 0),
            entry_price=price,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            hold_days=signal_config.hold_days,
            signal_type=signal_type,
            mode=m.get("mode", ""),
        ))
    return signals
```

- [ ] **Step 4: Run all signal tests**

Run: `.venv/bin/pytest tests/test_signal.py -v`
Expected: 7 passed (4 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add scanner/signal.py tests/test_signal.py
git commit -m "feat: extend TradeSignal for divergence mode with bearish support"
```

---

### Task 4: Add Mode Column to Tracker DB

**Files:**
- Modify: `scanner/tracker.py`

- [ ] **Step 1: Update _get_conn to include mode column**

In `scanner/tracker.py`, replace the `scan_results` CREATE TABLE statement (lines 17-27) with:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            market_cap_m REAL,
            drop_pct REAL NOT NULL,
            volume_ratio REAL NOT NULL,
            window_days INTEGER NOT NULL,
            score REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'accumulation',
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)
```

- [ ] **Step 2: Update save_scan to accept mode parameter**

Replace the `save_scan` function (lines 35-49):

```python
def save_scan(results: list[dict], mode: str = "accumulation") -> int:
    """保存一次扫描结果，返回scan_id"""
    conn = _get_conn()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("INSERT INTO scans (scan_time) VALUES (?)", (ts,))
    scan_id = cur.lastrowid
    for r in results:
        conn.execute(
            "INSERT INTO scan_results (scan_id, symbol, price, market_cap_m, drop_pct, volume_ratio, window_days, score, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, r["symbol"], r["price"], r.get("market_cap_m", 0),
             r["drop_pct"], r["volume_ratio"], r["window_days"], r["score"], mode),
        )
    conn.commit()
    conn.close()
    return scan_id
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `.venv/bin/pytest -v`
Expected: All 30 tests pass (existing 27 + 3 new signal tests)

- [ ] **Step 4: Commit**

```bash
git add scanner/tracker.py
git commit -m "feat: add mode column to scan_results table"
```

---

### Task 5: CLI Integration — run_divergence and --mode

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add run_divergence function to main.py**

After the existing `run()` function (after line 176), add:

```python
def run_divergence(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    from scanner.divergence import detect_divergence
    top_n = top_n or config.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/4] 获取OKX永续合约列表（Binance现货有K线的）...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉K线（背离模式需要90天）
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对，90天）...")
    klines = fetch_klines_batch(symbols, days=90, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 背离检测
    print("[3/4] MACD背离检测中...")
    matches = []
    for symbol, df in klines.items():
        result = detect_divergence(df)
        if result.divergence_type == "none":
            continue
        price = float(df["close"].iloc[-1])
        signal_type = "底背离" if result.divergence_type == "bullish" else "顶背离"
        matches.append({
            "symbol": symbol,
            "price": price,
            "drop_pct": 0,
            "volume_ratio": 0,
            "window_days": result.pivot_distance,
            "score": result.score,
            "signal_type": signal_type,
            "mode": "divergence",
        })

    print(f"       背离命中 {len(matches)} 个")

    if not matches:
        print("\n未找到MACD背离的币种。")
        return

    # Step 4: 市值过滤
    skip_cap = config.get("skip_market_cap_filter", False)
    if not symbols_override and not skip_cap:
        base_symbols = [m["symbol"].split("/")[0] for m in matches]
        print(f"[4/4] 查询 {len(base_symbols)} 个命中币种的市值...")
        market_caps = fetch_market_caps(base_symbols, page_delay=config.get("page_delay", 30))
        for m in matches:
            base = m["symbol"].split("/")[0]
            m["market_cap_m"] = market_caps.get(base, 0) / 1e6
        before = len(matches)
        matches = [m for m in matches if 0 < m["market_cap_m"] <= max_market_cap / 1e6]
        print(f"       市值过滤: {before} -> {len(matches)} 个 (< ${max_market_cap / 1e6:.0f}M)")
    else:
        print("[4/4] 跳过市值过滤")
        for m in matches:
            m["market_cap_m"] = 0

    if not matches:
        print("\n过滤后没有符合条件的币种。")
        return

    ranked = rank_results(matches, top_n=top_n)

    # 保存到数据库
    scan_id = save_scan(ranked, mode="divergence")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
            s.hold_days,
        ])

    headers = ["排名", "币种", "类型", "价格", "评分", "入场价", "止损价", "止盈价", "持仓天数"]
    print(f"\n找到 {len(signals)} 个交易信号（止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天）:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # 保存文件
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_data = [
        {
            "symbol": s.symbol,
            "signal_type": s.signal_type,
            "price": s.price,
            "score": s.score,
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
            "hold_days": s.hold_days,
        }
        for s in signals
    ]
    json_path = f"results/divergence_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/divergence_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"模式: MACD背离\n")
        f.write(f"信号参数: 止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天\n")
        f.write(f"找到 {len(signals)} 个交易信号:\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"结果已保存到 {json_path} 和 {txt_path}")
```

- [ ] **Step 2: Add --mode argument to main()**

Replace `main()` function (lines 292-316):

```python
def main():
    parser = argparse.ArgumentParser(description="币种形态筛选器")
    parser.add_argument("--mode", choices=["accumulation", "divergence"], default="accumulation",
                        help="扫描模式: accumulation=底部蓄力, divergence=MACD背离")
    parser.add_argument("--top", type=int, help="输出前N个结果")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--symbols", nargs="+", help="直接指定交易对")
    parser.add_argument("--track", action="store_true", help="查看所有跟踪中的币种")
    parser.add_argument("--history", type=str, help="查看某币种历史记录，如 ZIL/USDT")
    parser.add_argument("--backtest", action="store_true", help="运行回测验证形态有效性")
    parser.add_argument("--days", type=int, default=180, help="回测历史K线天数（默认180）")
    args = parser.parse_args()

    config, signal_config = load_config(args.config)

    if args.track:
        show_tracking()
    elif args.history:
        show_history(args.history)
    elif args.backtest:
        run_backtest_cli(config, days=args.days, symbols_override=args.symbols)
    elif args.mode == "divergence":
        run_divergence(config, signal_config, top_n=args.top, symbols_override=args.symbols)
    else:
        run(config, signal_config, top_n=args.top, symbols_override=args.symbols)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/pytest -v`
Expected: All 30 tests pass

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add --mode divergence CLI for MACD divergence scanning"
```

---

### Task 6: Final Integration Verification

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest -v`
Expected: 30 tests pass (10 divergence + 7 signal + 13 existing)

- [ ] **Step 2: Verify CLI help**

Run: `.venv/bin/python main.py --help`
Expected: Shows `--mode {accumulation,divergence}` option

- [ ] **Step 3: Commit any remaining changes**

If any fixes were needed, commit them.
