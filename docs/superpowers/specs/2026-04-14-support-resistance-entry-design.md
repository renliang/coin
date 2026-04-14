# 支撑/阻力位入场设计文档

**日期：** 2026-04-14  
**状态：** 已批准

---

## 背景

当前入场价由评分折扣决定（`entry = price × (1 - discount)`，discount 为 0.01~0.03），止损/止盈用 ATR 或固定百分比。这种方式忽略了市场结构，入场点与实际支撑位无关联。

本次改造引入 **Pivot 支撑/阻力位**，让入场价贴近支撑、止损放在支撑下方、止盈对齐阻力，同时保留原有逻辑作为兜底。

---

## 目标

- 入场价：最近有效支撑位上方 0.5%
- 止损价：支撑位下方 1 ATR（受 `max_stop_loss` 截断）
- 止盈价：最近有效阻力位下方 0.5%
- 找不到有效层级时，退回现有评分折扣逻辑，信号不中断

---

## 方案选择

| 方案 | 说明 | 结论 |
|------|------|------|
| Pivot 高低点 | 左右各 N 根 K 线局部极值 | **采用** |
| Volume Profile | 成交量密集区 | 日线数据精度不足，放弃 |
| 斐波那契回调 | 需先识别大涨大跌起止点 | 复杂度高，放弃 |
| 近期高低点 | 30/60 日最高/最低价 | 层级太少，放弃 |

---

## 架构

### 新增文件：`scanner/levels.py`

```python
def find_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 支撑位列表（升序）。
    判定：某根 K 线的 low 比左右各 left/right 根都低。
    数据不足时返回空列表。
    """

def find_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 阻力位列表（升序）。"""

def nearest_support(df: pd.DataFrame, price: float, max_dist: float) -> float | None:
    """返回距 price 最近且在 price 下方、距离 ≤ max_dist 的支撑位。找不到返回 None。"""

def nearest_resistance(df: pd.DataFrame, price: float) -> float | None:
    """返回高于 price 的最近阻力位。找不到返回 None。"""
```

**Pivot 窗口：** 左右各 5 根 K 线（约一周日线，过滤噪音）。

### 修改文件：`scanner/signal.py`

`generate_signals()` 新增可选参数：

```python
def generate_signals(
    matches: list[dict],
    signal_config: SignalConfig,
    klines_map: dict[str, pd.DataFrame] | None = None,
) -> list[TradeSignal]:
```

`TradeSignal` 新增字段：

```python
entry_method: str = ""  # "support_resistance" | "score_discount"
```

### 修改文件：`main.py`

调用 `generate_signals()` 时透传 `klines_map`，改动 < 5 行。

输出表格新增标识列：`[SR]`（支撑阻力路径）vs `[SD]`（评分折扣路径）。

---

## 计算逻辑

### 多头信号（底部蓄力 / 底背离）

```
support = nearest_support(df, price, max_dist=signal_config.max_stop_loss)
resistance = nearest_resistance(df, price)

if support is not None and resistance is not None and resistance > support:
    entry     = support × 1.005          # 支撑上方 0.5%
    sl_price  = support - 1 × ATR        # 破结构止损
    tp_price  = resistance × 0.995       # 阻力下方 0.5%
    entry_method = "support_resistance"
else:
    # 退回原有折扣逻辑
    entry_method = "score_discount"
```

止损截断：与现有逻辑一致，若 `|sl_price - entry| / entry > max_stop_loss`，收紧到 `entry × (1 - max_stop_loss)`，`sl_capped = True`。

### 空头信号（顶背离）

对称处理：`nearest_resistance` 找卖出点，`nearest_support` 找止盈目标，方向互换。

---

## 降级条件

支撑/阻力路径降级到原逻辑的条件（满足任一）：

1. `klines_map` 未传入
2. 该 symbol 的 df 不在 `klines_map` 中
3. `nearest_support` 返回 None（支撑距离 > `max_stop_loss` 或不存在）
4. `nearest_resistance` 返回 None（找不到高于入场价的阻力）
5. `resistance <= support`（无盈利空间）

---

## 测试计划

### `tests/test_levels.py`（新增）

- Pivot 低点识别：合成标准 V 形 df，验证低点坐标正确
- Pivot 高点识别：合成标准倒 V 形 df，验证高点坐标正确
- 距离过滤：支撑超出 `max_stop_loss` 时 `nearest_support` 返回 None
- 数据不足：df 行数 < `left + right + 1` 时返回空列表，不抛异常
- 多层级排序：多个支撑位时返回距 price 最近的那个

### `tests/test_signal.py`（更新）

- 传入含有效支撑/阻力的 df → `entry_method == "support_resistance"`，入场/止损/止盈符合预期
- 支撑太远 → 退回折扣逻辑，`entry_method == "score_discount"`
- 找不到阻力 → 退回折扣逻辑
- 空头信号方向正确

---

## 不变范围

- `scanner/detector.py` — 不变
- `scanner/scorer.py` — 不变
- `scanner/divergence.py` — 不变
- `config.yaml` — 无新参数，`max_stop_loss` 复用
- `history_ui/` — 不变
- 现有 ATR 止损截断逻辑 — 复用，不重写
