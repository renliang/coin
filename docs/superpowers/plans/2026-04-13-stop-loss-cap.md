# Stop-Loss Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ATR 止损加硬上限（默认 5%），超过时自动截断并在输出中标注 `[已收紧]`。

**Architecture:** 在 `SignalConfig` 加 `max_stop_loss` 字段，在 `TradeSignal` 加 `sl_capped` 布尔字段，`generate_signals()` ATR 路径计算完止损价后检查并截断，`main.py` 各输出函数读取 `sl_capped` 追加标注。

**Tech Stack:** Python 3.13 / dataclasses / pytest

---

## 文件地图

| 操作 | 文件 | 改动内容 |
|------|------|---------|
| Modify | `scanner/signal.py` | `SignalConfig` 加 `max_stop_loss`；`TradeSignal` 加 `sl_capped`；`generate_signals()` 加截断逻辑 |
| Modify | `config.yaml` | `signal` 段加 `max_stop_loss: 0.05` |
| Modify | `main.py` | `load_config()` 读取 `max_stop_loss`；`run()` 和 `run_divergence()` 输出止损价时追加 `[已收紧]` |
| Modify | `tests/test_signal.py` | 新增三个截断相关测试 |

---

## Task 1: 为 `SignalConfig` 和 `TradeSignal` 新增字段，写失败测试

**Files:**
- Modify: `scanner/signal.py:7-17`（`SignalConfig`）、`scanner/signal.py:35-48`（`TradeSignal`）
- Test: `tests/test_signal.py`

- [ ] **Step 1: 在 `tests/test_signal.py` 末尾追加三个失败测试**

```python
def test_sl_capped_when_atr_exceeds_limit():
    """ATR 止损超出 max_stop_loss 时，止损被截断且 sl_capped=True。"""
    # price=100, score=0.70 → entry=97.5, ATR=10 → raw_sl=97.5-2*10=77.5 (距离20.5%) > 5%
    # capped: sl = 97.5 * (1 - 0.05) = 92.625
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 10.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is True
    assert abs(s.stop_loss_price - 92.625) < 0.01   # 97.5 * 0.95


def test_sl_not_capped_when_within_limit():
    """ATR 止损在 max_stop_loss 以内时，止损不截断且 sl_capped=False。"""
    # price=100, score=0.70 → entry=97.5, ATR=2 → raw_sl=93.5 (距离4.1%) < 5%
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 2.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is False
    assert abs(s.stop_loss_price - 93.5) < 0.01   # 97.5 - 2*2.0，未截断


def test_bearish_sl_capped():
    """顶背离 ATR 止损超出 max_stop_loss 时截断，sl_capped=True。"""
    # price=100, score=0.70 → entry=102.5, ATR=10 → raw_sl=122.5 (距离19.5%) > 5%
    # capped: sl = 102.5 * (1 + 0.05) = 107.625
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 10.0,
         "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
         "signal_type": "顶背离", "mode": "divergence"},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is True
    assert abs(s.stop_loss_price - 107.625) < 0.01   # 102.5 * 1.05
```

- [ ] **Step 2: 运行这三个测试，确认 FAIL（字段还未定义）**

```bash
cd /Users/edy/Desktop/workspace/coin && .venv/bin/pytest tests/test_signal.py::test_sl_capped_when_atr_exceeds_limit tests/test_signal.py::test_sl_not_capped_when_within_limit tests/test_signal.py::test_bearish_sl_capped -v
```

预期：3 个测试均 FAIL，报 `TypeError` 或 `AttributeError`（`max_stop_loss` / `sl_capped` 未定义）

- [ ] **Step 3: 在 `scanner/signal.py` 的 `SignalConfig` 中加入 `max_stop_loss` 字段**

将 `SignalConfig` 替换为：

```python
@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0
    atr_tp_multiplier: float = 3.0
    confirmation: bool = True
    confirmation_min_pass: int = 4
    max_stop_loss: float = 0.05
```

- [ ] **Step 4: 在 `scanner/signal.py` 的 `TradeSignal` 中加入 `sl_capped` 字段**

将 `TradeSignal` 替换为：

```python
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
```

- [ ] **Step 5: 运行全量测试，确认字段加入后旧测试仍然通过，新测试仍然 FAIL（截断逻辑还未加）**

```bash
.venv/bin/pytest tests/test_signal.py -v
```

预期：原有 10 个测试 PASS，新增 3 个测试 FAIL（`sl_capped` 默认 False，截断未触发）

- [ ] **Step 6: Commit**

```bash
git add scanner/signal.py tests/test_signal.py
git commit -m "feat: add max_stop_loss to SignalConfig and sl_capped to TradeSignal"
```

---

## Task 2: 在 `generate_signals()` 中加入截断逻辑

**Files:**
- Modify: `scanner/signal.py:62-111`（`generate_signals()` 函数）

- [ ] **Step 1: 在 `scanner/signal.py` 中，`generate_signals()` 的 ATR 路径计算止损价之后加入截断逻辑**

将 `generate_signals()` 函数的主循环部分（从 `discount = _entry_discount(score)` 开始到 `signals.append(...)` 之前）替换为：

```python
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

        # ATR 止损截断：若止损距离超过 max_stop_loss，收紧到上限
        sl_capped = False
        if use_atr:
            sl_dist = abs(sl_price - entry) / entry
            if sl_dist > signal_config.max_stop_loss:
                if is_bearish:
                    sl_price = entry * (1 + signal_config.max_stop_loss)
                else:
                    sl_price = entry * (1 - signal_config.max_stop_loss)
                sl_capped = True
```

并在 `signals.append(TradeSignal(...))` 调用中加入 `sl_capped=sl_capped`：

```python
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
        ))
```

- [ ] **Step 2: 运行全量 signal 测试，3 个新测试应全部通过**

```bash
.venv/bin/pytest tests/test_signal.py -v
```

预期：全部 13 个测试 PASS

- [ ] **Step 3: Commit**

```bash
git add scanner/signal.py
git commit -m "feat: cap ATR stop-loss at max_stop_loss and set sl_capped flag"
```

---

## Task 3: 更新 `load_config()` + `config.yaml`

**Files:**
- Modify: `main.py:75-85`（`load_config()` 中的 `SignalConfig` 构造）
- Modify: `config.yaml`

- [ ] **Step 1: 在 `main.py` 的 `load_config()` 中，`SignalConfig` 构造加入 `max_stop_loss`**

将以下代码：

```python
    signal_config = SignalConfig(
        min_score=sig.get("min_score", 0.6),
        hold_days=sig.get("hold_days", 3),
        stop_loss=sig.get("stop_loss", 0.05),
        take_profit=sig.get("take_profit", 0.08),
        atr_period=sig.get("atr_period", 14),
        atr_sl_multiplier=sig.get("atr_sl_multiplier", 2.0),
        atr_tp_multiplier=sig.get("atr_tp_multiplier", 3.0),
        confirmation=sig.get("confirmation", True),
        confirmation_min_pass=sig.get("confirmation_min_pass", 3),
    )
```

替换为：

```python
    signal_config = SignalConfig(
        min_score=sig.get("min_score", 0.6),
        hold_days=sig.get("hold_days", 3),
        stop_loss=sig.get("stop_loss", 0.05),
        take_profit=sig.get("take_profit", 0.08),
        atr_period=sig.get("atr_period", 14),
        atr_sl_multiplier=sig.get("atr_sl_multiplier", 2.0),
        atr_tp_multiplier=sig.get("atr_tp_multiplier", 3.0),
        confirmation=sig.get("confirmation", True),
        confirmation_min_pass=sig.get("confirmation_min_pass", 3),
        max_stop_loss=sig.get("max_stop_loss", 0.05),
    )
```

- [ ] **Step 2: 在 `config.yaml` 的 `signal` 段加入 `max_stop_loss`**

读取 `config.yaml`，在 `signal` 段中找到 `atr_sl_multiplier` 行，在其下方加入：

```yaml
  max_stop_loss: 0.05          # ATR 止损距离上限（相对入场价比例）
```

- [ ] **Step 3: 运行全量测试确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -10
```

预期：所有测试通过

- [ ] **Step 4: Commit**

```bash
git add main.py config.yaml
git commit -m "feat: read max_stop_loss from config and pass to SignalConfig"
```

---

## Task 4: 更新输出函数，止损被截断时追加 `[已收紧]`

**Files:**
- Modify: `main.py:240-254`（`run()` 输出）
- Modify: `main.py:398-414`（`run_divergence()` 输出）

注：`run_breakout()` 会在 `generate_signals()` 之后直接覆写 `stop_loss_price`（使用回踩低点 × 0.97），`sl_capped` 对 breakout 无意义，不修改。

- [ ] **Step 1: 更新 `run()` 中的止损价输出（accumulation 模式）**

将 `run()` 函数中 `table_data.append` 的止损价格式化行：

```python
            f"{s.stop_loss_price:.4f}",
```

（位于 `f"{s.entry_price:.4f}",` 下方，`f"{s.take_profit_price:.4f}",` 上方，是 table_data 的第 6 个元素）

替换为：

```python
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
```

- [ ] **Step 2: 更新 `run_divergence()` 中的止损价输出（divergence 模式）**

将 `run_divergence()` 函数中 `table_data.append` 的止损价格式化行（位于 `f"{s.entry_price:.4f}",` 下方，`f"{s.take_profit_price:.4f}",` 上方）：

```python
            f"{s.stop_loss_price:.4f}",
```

替换为：

```python
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
```

- [ ] **Step 3: 运行全量测试确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -10
```

预期：所有测试通过

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: show [已收紧] in output when ATR stop-loss is capped"
```

---

## Task 5: 全量测试 + push

- [ ] **Step 1: 运行全部测试**

```bash
.venv/bin/pytest tests/ -v
```

预期：所有测试通过（在 Task 1-4 基础上新增 3 个，共 132 个）

- [ ] **Step 2: 查看提交记录**

```bash
git log --oneline -5
```

- [ ] **Step 3: Push**

```bash
git push origin main
```
