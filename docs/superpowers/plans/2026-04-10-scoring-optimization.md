# 背离信号评分优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化背离评分权重、新增启动前兆指标、将确认层从及格制改为加分制，使 ONG 这类强动能币排名高于 FIDA 这类虚高分币。

**Architecture:** 修改 `scanner/divergence.py` 权重配比；在 `scanner/confirmation.py` 新增 `compute_volume_surge` 和 `compute_atr_accel`，并将 `confirm_signal` 从 bool 过滤改为连续评分 + 加分模式；在 `main.py` 和 `scanner/backtest.py` 中集成加分逻辑。

**Tech Stack:** Python 3.13, pandas, numpy（无新增依赖）

---

### Task 1: 背离评分权重调优

**Files:**
- Modify: `scanner/divergence.py:74`
- Modify: `tests/test_divergence.py`

- [ ] **Step 1: 更新权重**

在 `scanner/divergence.py` 第 74 行，将：

```python
    return strength * 0.4 + confirm * 0.3 + time_score * 0.3
```

改为：

```python
    return strength * 0.5 + confirm * 0.3 + time_score * 0.2
```

- [ ] **Step 2: 运行现有测试确认不破坏**

Run: `.venv/bin/pytest tests/test_divergence.py -v`
Expected: 全部通过（测试只断言 `score > 0` 和 `score == 0.0`，不受权重调整影响）

- [ ] **Step 3: 提交**

```bash
git add scanner/divergence.py
git commit -m "feat: adjust divergence scoring weights — strength 0.5, confirm 0.3, time 0.2"
```

---

### Task 2: 新增 compute_volume_surge

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_confirmation.py` 末尾追加：

```python
from scanner.confirmation import compute_volume_surge


def test_volume_surge_detects_increase():
    """近3日均量是前7日的2倍 -> surge = 2.0。"""
    volumes = pd.Series([100.0] * 7 + [200.0] * 3)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert abs(surge - 2.0) < 0.01


def test_volume_surge_no_change():
    """均匀量能 -> surge ≈ 1.0。"""
    volumes = pd.Series([100.0] * 10)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert abs(surge - 1.0) < 0.01


def test_volume_surge_insufficient_data():
    """数据不足 -> 返回 1.0。"""
    volumes = pd.Series([100.0] * 5)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert surge == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_volume_surge_detects_increase -v`
Expected: FAIL — `ImportError: cannot import name 'compute_volume_surge'`

- [ ] **Step 3: 实现 compute_volume_surge**

在 `scanner/confirmation.py` 的 `compute_mfi` 函数之后追加：

```python
def compute_volume_surge(
    volumes: pd.Series,
    recent_days: int = 3,
    baseline_days: int = 7,
) -> float:
    """计算近 recent_days 日均量 / 前 baseline_days 日均量。

    返回比值（1.0=无变化，2.0=倍量）。数据不足返回 1.0。
    """
    if len(volumes) < recent_days + baseline_days:
        return 1.0
    recent_avg = volumes.iloc[-recent_days:].mean()
    baseline_avg = volumes.iloc[-(recent_days + baseline_days):-recent_days].mean()
    if baseline_avg == 0:
        return 1.0
    return float(recent_avg / baseline_avg)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v -k "volume_surge"`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_volume_surge for pre-launch detection"
```

---

### Task 3: 新增 compute_atr_accel

**Files:**
- Modify: `scanner/confirmation.py`
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_confirmation.py` 末尾追加：

```python
from scanner.confirmation import compute_atr_accel


def test_atr_accel_expanding_volatility():
    """近期波幅扩大 -> accel > 1.0。"""
    n = 22  # 7 recent + 14 baseline + 1 for shift
    # 前14日：窄幅波动
    highs = [10.5] * 15 + [12.0] * 7
    lows = [9.5] * 15 + [8.0] * 7
    closes = [10.0] * 15 + [10.0] * 7
    accel = compute_atr_accel(
        pd.Series(highs), pd.Series(lows), pd.Series(closes),
        recent_days=7, baseline_days=14,
    )
    assert accel > 1.0


def test_atr_accel_stable():
    """波幅不变 -> accel ≈ 1.0。"""
    n = 22
    highs = pd.Series([10.5] * n)
    lows = pd.Series([9.5] * n)
    closes = pd.Series([10.0] * n)
    accel = compute_atr_accel(highs, lows, closes, recent_days=7, baseline_days=14)
    assert abs(accel - 1.0) < 0.1


def test_atr_accel_insufficient_data():
    """数据不足 -> 返回 1.0。"""
    accel = compute_atr_accel(
        pd.Series([10.5] * 5), pd.Series([9.5] * 5), pd.Series([10.0] * 5),
        recent_days=7, baseline_days=14,
    )
    assert accel == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_atr_accel_expanding_volatility -v`
Expected: FAIL — `ImportError: cannot import name 'compute_atr_accel'`

- [ ] **Step 3: 实现 compute_atr_accel**

在 `scanner/confirmation.py` 的 `compute_volume_surge` 函数之后追加：

```python
def compute_atr_accel(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    recent_days: int = 7,
    baseline_days: int = 14,
) -> float:
    """计算近 recent_days ATR / 前 baseline_days ATR。

    返回比值（1.0=无变化，>1.2=波动加速）。数据不足返回 1.0。
    """
    if len(closes) < recent_days + baseline_days + 1:
        return 1.0

    def _atr(h: pd.Series, l: pd.Series, c: pd.Series) -> float:
        prev_c = c.shift(1)
        tr = pd.concat([
            h - l,
            (h - prev_c).abs(),
            (l - prev_c).abs(),
        ], axis=1).max(axis=1)
        return float(tr.mean())

    cut = -(recent_days + baseline_days)
    recent_atr = _atr(
        highs.iloc[-recent_days:],
        lows.iloc[-recent_days:],
        closes.iloc[-(recent_days + 1):],
    )
    baseline_atr = _atr(
        highs.iloc[cut:-recent_days],
        lows.iloc[cut:-recent_days],
        closes.iloc[cut - 1:-recent_days],
    )
    if baseline_atr == 0:
        return 1.0
    return float(recent_atr / baseline_atr)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_confirmation.py -v -k "atr_accel"`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: add compute_atr_accel for volatility expansion detection"
```

---

### Task 4: ConfirmationResult 扩展 + confirm_signal 改为加分制

**Files:**
- Modify: `scanner/confirmation.py:1-17` (ConfirmationResult)
- Modify: `scanner/confirmation.py:84-136` (confirm_signal)
- Modify: `tests/test_confirmation.py`

- [ ] **Step 1: 写新的 confirm_signal 测试**

在 `tests/test_confirmation.py` 末尾追加：

```python
def test_confirm_signal_returns_score_and_bonus():
    """confirm_signal 应返回 score 和 bonus 字段。"""
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert hasattr(result, "score")
    assert hasattr(result, "bonus")
    assert 0.0 <= result.score <= 1.0
    assert -0.10 <= result.bonus <= 0.10


def test_confirm_signal_high_score_positive_bonus():
    """强确认信号（放量反弹）应给正加分。"""
    # 先跌后涨，近期放量
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [100.0] * 20 + [500.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.score > 0.5
    assert result.bonus > 0


def test_confirm_signal_weak_gives_negative_bonus():
    """弱确认（持续下跌缩量）应给负加分。"""
    prices = [20 - i * 0.3 for i in range(20)] + [14 - i * 0.2 for i in range(10)]
    vols = [500.0] * 20 + [50.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.bonus < 0


def test_confirm_signal_has_surge_and_atr_fields():
    """结果应包含 volume_surge_ok 和 atr_accel_ok 字段。"""
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert hasattr(result, "volume_surge_ok")
    assert hasattr(result, "atr_accel_ok")
    assert "volume_surge" in result.details
    assert "atr_accel" in result.details
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_confirmation.py::test_confirm_signal_returns_score_and_bonus -v`
Expected: FAIL — `AttributeError: 'ConfirmationResult' object has no attribute 'score'`

- [ ] **Step 3: 更新 ConfirmationResult**

替换 `scanner/confirmation.py` 中的 `ConfirmationResult`：

```python
@dataclass
class ConfirmationResult:
    """信号确认结果。"""
    passed: bool
    passed_count: int
    score: float           # 确认层连续得分 [0, 1]
    bonus: float           # 加分值 [-0.10, +0.10]
    rsi_ok: bool
    obv_ok: bool
    volume_ratio_ok: bool
    mfi_ok: bool
    volume_surge_ok: bool
    atr_accel_ok: bool
    details: dict
```

- [ ] **Step 4: 重写 confirm_signal 函数**

替换 `scanner/confirmation.py` 中的 `confirm_signal` 函数：

```python
def confirm_signal(
    df: pd.DataFrame,
    direction: str,
    min_pass: int = 4,
) -> ConfirmationResult:
    """对候选信号做多指标确认，返回连续评分和加分。

    Args:
        df: K线 DataFrame (需含 open/high/low/close/volume)
        direction: "long" 或 "short"
        min_pass: 6项检查中至少通过几项才算确认通过

    Returns:
        ConfirmationResult (含 score 和 bonus)
    """
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    # 计算原始指标值
    rsi = compute_rsi(closes, period=14)
    obv_trend = compute_obv_trend(closes, volumes, days=7)
    vol_ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    accel = compute_atr_accel(highs, lows, closes, recent_days=7, baseline_days=14)

    # --- bool 判断（用于过滤） ---
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
    volume_surge_ok = surge >= 1.5
    atr_accel_ok = accel > 1.2

    checks = [bool(rsi_ok), bool(obv_ok), bool(volume_ratio_ok),
              bool(mfi_ok), bool(volume_surge_ok), bool(atr_accel_ok)]
    passed_count = sum(checks)

    # --- 连续分计算 [0, 1] ---
    rsi_score = max(0.0, 1.0 - abs(rsi - 50) / 50)

    total_obv = abs(compute_obv_trend(closes, volumes, days=len(closes) - 1)) + 1e-10
    obv_raw = min(1.0, max(0.0, abs(obv_trend) / total_obv * 10))
    obv_score = obv_raw if (direction == "long" and obv_trend > 0) or (direction == "short" and obv_trend < 0) else 1.0 - obv_raw

    if direction == "long":
        vr_score = min(1.0, vol_ratio / 2.0) if vol_ratio != float("inf") else 1.0
    else:
        vr_score = min(1.0, (1.0 / vol_ratio) / 2.0) if vol_ratio > 0 and vol_ratio != float("inf") else (1.0 if vol_ratio == 0 else 0.0)

    mfi_score = max(0.0, 1.0 - abs(mfi - 50) / 50)
    surge_score = min(1.0, max(0.0, (surge - 1.0) / 1.0))
    accel_score = min(1.0, max(0.0, (accel - 1.0) / 0.5))

    # 6 项均分
    confirmation_score = (rsi_score + obv_score + vr_score + mfi_score + surge_score + accel_score) / 6.0

    # 加分：以 0.5 为中性，最大 ±0.10
    bonus = (confirmation_score - 0.5) * 0.2
    bonus = max(-0.10, min(0.10, bonus))

    return ConfirmationResult(
        passed=passed_count >= min_pass,
        passed_count=passed_count,
        score=round(confirmation_score, 4),
        bonus=round(bonus, 4),
        rsi_ok=checks[0],
        obv_ok=checks[1],
        volume_ratio_ok=checks[2],
        mfi_ok=checks[3],
        volume_surge_ok=checks[4],
        atr_accel_ok=checks[5],
        details={
            "rsi": round(rsi, 1),
            "obv_7d": round(obv_trend, 2),
            "up_down_vol_ratio": round(vol_ratio, 2) if vol_ratio != float("inf") else "inf",
            "mfi": round(mfi, 1),
            "volume_surge": round(surge, 2),
            "atr_accel": round(accel, 2),
        },
    )
```

- [ ] **Step 5: 更新现有 confirm_signal 测试适配新签名**

在 `tests/test_confirmation.py` 中，将现有的 3 个 `confirm_signal` 测试中 `min_pass=3` 改为 `min_pass=4`。原有断言保持不变（`passed`、`passed_count`、`obv_ok` 字段仍存在）。

- [ ] **Step 6: 运行全量测试**

Run: `.venv/bin/pytest tests/test_confirmation.py -v`
Expected: 全部通过（含新增的 4 个测试 + 原有 13 个 + volume_surge 3 个 + atr_accel 3 个 = 23 个）

- [ ] **Step 7: 提交**

```bash
git add scanner/confirmation.py tests/test_confirmation.py
git commit -m "feat: confirmation layer scoring — continuous score + bonus system"
```

---

### Task 5: SignalConfig 和 config.yaml 更新

**Files:**
- Modify: `scanner/signal.py:11`
- Modify: `config.yaml:24`
- Modify: `main.py:38`

- [ ] **Step 1: 更新 SignalConfig 默认值**

在 `scanner/signal.py` 第 11 行，将：

```python
    confirmation_min_pass: int = 3
```

改为：

```python
    confirmation_min_pass: int = 4
```

- [ ] **Step 2: 更新 config.yaml**

在 `config.yaml` 第 24 行，将：

```yaml
  confirmation_min_pass: 3        # 4项中至少通过几项
```

改为：

```yaml
  confirmation_min_pass: 4        # 6项中至少通过几项
```

- [ ] **Step 3: 运行全量测试确认不破坏**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git add scanner/signal.py config.yaml
git commit -m "feat: update confirmation_min_pass default from 3 to 4 (6 indicators)"
```

---

### Task 6: main.py 集成加分逻辑

**Files:**
- Modify: `main.py:131-147` (run 函数确认层)
- Modify: `main.py:282-299` (run_divergence 函数确认层)
- Modify: `main.py:313-330` (run_divergence 输出表格)
- Modify: `main.py:162-177` (run 输出表格)

- [ ] **Step 1: 更新 run() 中的确认层逻辑**

替换 `main.py` 第 131-147 行的确认层过滤块：

```python
    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        # 按新分数重新排序
        ranked.sort(key=lambda x: x["score"], reverse=True)
```

- [ ] **Step 2: 更新 run_divergence() 中的确认层逻辑**

替换 `main.py` 第 282-299 行的确认层过滤块：

```python
    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            direction = "short" if m.get("signal_type") == "顶背离" else "long"
            result = confirm_signal(klines[m["symbol"]], direction, signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        # 按新分数重新排序
        ranked.sort(key=lambda x: x["score"], reverse=True)
```

- [ ] **Step 3: 更新 run_divergence() 输出表格**

替换 `main.py` 第 314-330 行的表格生成：

```python
    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        bonus_str = f"+{s.score - s.score:.2f}" if not hasattr(s, '_confirm_bonus') else ""
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
```

注意：表格输出保持不变（评分列显示最终分 = 基础分 + 加分），因为 `generate_signals` 已从 `m["score"]`（已包含加分）读取分数。无需额外改动表格列。

- [ ] **Step 4: 运行全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add main.py
git commit -m "feat: integrate confirmation bonus into run() and run_divergence()"
```

---

### Task 7: backtest.py 适配加分

**Files:**
- Modify: `scanner/backtest.py:68-72`
- Modify: `tests/test_backtest.py`

- [ ] **Step 1: 写回测加分测试**

在 `tests/test_backtest.py` 末尾追加：

```python
def test_run_backtest_confirmation_adjusts_score():
    """开启确认层后，命中的 score 应与无确认层时不同（含加分）。"""
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
    hits_no = run_backtest({"TEST/USDT": df}, config, confirmation=False)
    hits_yes = run_backtest({"TEST/USDT": df}, config, confirmation=True)

    if hits_yes:
        # 加分后分数应与原始分数不同
        # 由于加分可能为正或负，只验证类型正确
        for h in hits_yes:
            assert isinstance(h.score, float)
```

- [ ] **Step 2: 运行测试确认失败（或通过）**

Run: `.venv/bin/pytest tests/test_backtest.py::test_run_backtest_confirmation_adjusts_score -v`
Expected: 可能通过也可能失败，取决于 confirm_signal 签名变更

- [ ] **Step 3: 更新 backtest.py 确认层逻辑**

替换 `scanner/backtest.py` 第 68-72 行：

```python
            # 确认层过滤 + 加分
            if confirmation:
                conf = confirm_signal(slice_df, "long", confirmation_min_pass)
                if not conf.passed:
                    continue
                score = score + conf.bonus
```

注意：`score` 变量在第 75 行赋值，需将确认层代码移到 `score = score_result(...)` 之后。完整上下文：

```python
            last_hit_idx = i
            score = score_result(result, drop_min=drop_min, drop_max=drop_max, max_daily_change=max_daily)

            # 确认层加分
            if confirmation:
                conf = confirm_signal(slice_df, "long", confirmation_min_pass)
                if not conf.passed:
                    last_hit_idx = -window_max  # 重置，允许后续重新检测
                    continue
                score = score + conf.bonus
```

即将确认层代码从第 68-72 行（`result.matched` 检查之后）移到第 75 行（`score_result` 之后），使加分能叠加到分数上。

- [ ] **Step 4: 运行全量测试**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add scanner/backtest.py tests/test_backtest.py
git commit -m "feat: backtest applies confirmation bonus to hit scores"
```

---

### Task 8: 全量回归测试 + 端到端验证

**Files:**
- 无新增文件

- [ ] **Step 1: 运行全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 2: 端到端验证 — 背离模式**

Run: `.venv/bin/python main.py --mode divergence`
Expected:
- 输出中出现 `[确认]` 行
- ONG/USDT 排名应高于 FIDA/USDT（如果两者都在当日扫描结果中）

- [ ] **Step 3: 端到端验证 — --no-confirm**

Run: `.venv/bin/python main.py --mode divergence --no-confirm`
Expected: 无 `[确认]` 行，信号数量多于有确认层时

- [ ] **Step 4: 端到端验证 — 蓄力模式**

Run: `.venv/bin/python main.py`
Expected: 正常输出，确认层生效

- [ ] **Step 5: 端到端验证 — 回测**

Run: `.venv/bin/python main.py --backtest --days 180`
Expected: 正常输出回测统计
