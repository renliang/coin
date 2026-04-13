# 止损上限设计文档

**日期：** 2026-04-13  
**状态：** 已批准  
**范围：** `scanner/signal.py` + `config.yaml` + `main.py` 输出层

---

## 背景与目标

现有止损逻辑使用 ATR × 2.0 计算止损距离。当市场波动较大时，ATR 本身偏大，导致止损距离动辄 8-15%，实际亏损风险超出预期。

目标：为 ATR 止损加一个硬上限（默认 5%），超过上限时自动截断，并在信号输出中标注"已收紧"，方便复盘。

---

## 改动范围

| 文件 | 改动内容 |
|------|---------|
| `scanner/signal.py` | `SignalConfig` 新增 `max_stop_loss`；`TradeSignal` 新增 `sl_capped`；`generate_signals()` 加截断逻辑 |
| `config.yaml` | `signal` 段新增 `max_stop_loss: 0.05` |
| `main.py` | 各模式输出止损价时，若 `sl_capped=True` 追加 `[已收紧]` |

---

## 数据结构

### `SignalConfig` 新增字段

```python
max_stop_loss: float = 0.05  # 止损距离上限（相对入场价比例），默认 5%
```

在 `config.yaml` 的 `signal` 段可覆盖：

```yaml
signal:
  max_stop_loss: 0.05  # 止损最大 5%
```

### `TradeSignal` 新增字段

```python
sl_capped: bool = False  # ATR 止损是否被截断到 max_stop_loss
```

---

## 核心逻辑：`generate_signals()`

ATR 路径计算出 `sl_price` 后，立即做截断检查：

```python
sl_dist = abs(sl_price - entry) / entry
sl_capped = False

if sl_dist > signal_config.max_stop_loss:
    if is_bearish:
        sl_price = entry * (1 + signal_config.max_stop_loss)
    else:
        sl_price = entry * (1 - signal_config.max_stop_loss)
    sl_capped = True
```

**作用范围**：仅对 ATR 路径（`use_atr=True`）生效。固定比例回退路径本身就是 `stop_loss=5%`，不需要截断。

`sl_capped` 写入 `TradeSignal`。

---

## 输出标注

`main.py` 中打印止损价的位置，若 `signal.sl_capped is True`，在止损行末追加 ` [已收紧]`：

```
止损: 0.0421  [已收紧]
```

三个扫描模式（accumulation、divergence、breakout）的输出函数均需更新。JSON/TXT 结果文件不做专门格式化，`sl_capped` 字段随信号自然序列化。

---

## 不在范围内

- 不修改 ATR 乘数（`atr_sl_multiplier`）
- 不修改 Take Profit 逻辑
- 不修改固定比例回退路径
- 不为截断事件单独记录日志（输出标注已足够）
