# 止损-杠杆联动风控设计

**日期:** 2026-04-12
**状态:** 已批准

## 问题

现有系统使用交易所允许的最大杠杆（`get_max_leverage`），但止损距离（5% 或 ATR×2）与杠杆之间没有约束关系。高杠杆下爆仓价比止损价更近，导致止损未触发就被强平。

例：某币最大杠杆 75x，止损 5%。保证金率 1/75 ≈ 1.33%，价格跌 1.33% 即爆仓，止损形同虚设。

## 方案：止损距离反推杠杆 + 评分分档

### 核心公式

```
止损距离 = |entry_price - stop_loss_price| / entry_price
最大安全杠杆 = floor(1 / (止损距离 × safety_factor))
实际杠杆 = min(最大安全杠杆 × score_leverage_pct, max_leverage, exchange_max_leverage)
```

- `safety_factor`: 1.5（安全系数，保证爆仓距离 = 止损距离 × 1.5）
- `max_leverage`: 20（全局硬上限）
- 杠杆 < 1 时不开仓

### 评分 → 杠杆系数分档

| 评分区间 | score_leverage_pct | 说明 |
|---------|-------------------|------|
| >= 0.9  | 1.0 (100%)        | 高信心，用满安全杠杆 |
| >= 0.8  | 0.8 (80%)         | 中高信心 |
| >= 0.7  | 0.6 (60%)         | 中等信心 |
| >= 0.6  | 0.4 (40%)         | 刚过门槛，保守 |

### 示例

| 币种 | 止损距离 | 安全杠杆上限 | 评分 | 系数 | 实际杠杆 |
|------|---------|-------------|------|------|---------|
| BTC  | 3%      | 22x → cap 20x | 0.85 | 80% | 16x |
| 山寨A | 5%     | 13x         | 0.7  | 60% | 7x |
| 山寨B | 10%    | 6x          | 0.65 | 40% | 2x |
| 山寨C | 15%    | 4x          | 0.6  | 40% | 1x |

## 配置变更（config.yaml）

```yaml
trading:
  safety_factor: 1.5              # 爆仓距离 = 止损距离 × 此值
  max_leverage: 20                # 全局杠杆硬上限
  score_leverage:                 # 评分 → 杠杆系数（取 <= score 的最大阈值）
    0.6: 0.4
    0.7: 0.6
    0.8: 0.8
    0.9: 1.0
  # 以下保持不变
  score_sizing:
    0.6: 0.02
    0.7: 0.03
    0.8: 0.04
    0.9: 0.05
```

## 代码变更

### 1. `scanner/trader/sizing.py`

- 新增 `calculate_leverage(stop_distance, score, score_leverage, safety_factor, max_leverage, exchange_max)` 函数
- `get_max_leverage()` 保留但不再作为下单杠杆来源，仅用于查询交易所上限
- `calculate_position()` 签名不变，调用方传入新算出的 leverage

### 2. `main.py`

下单循环改为：

```python
exchange_max = get_max_leverage(exchange, signal.symbol)
stop_distance = abs(signal.entry_price - signal.stop_loss_price) / signal.entry_price
leverage = calculate_leverage(
    stop_distance=stop_distance,
    score=signal.score,
    score_leverage=trading_config.score_leverage,
    safety_factor=trading_config.safety_factor,
    max_leverage=trading_config.max_leverage,
    exchange_max=exchange_max,
)
if leverage < 1:
    logger.warning("[%s] 止损距离 %.1f%% 过大，安全杠杆<1，跳过", symbol, stop_distance*100)
    continue
```

### 3. 不改动的文件

- `scanner/signal.py` — 止损/止盈计算逻辑不变
- `scanner/trader/executor.py` — 接收 leverage 参数，不关心来源

## 风控保障链

```
ATR/固定比例 → 止损距离
    → 反推最大安全杠杆（÷ safety_factor 1.5）
        → × 评分系数（0.4~1.0）
            → cap 全局上限 20x & 交易所上限
                → 仓位 = 余额 × score_sizing_pct × leverage / price
```

每一层都是递减约束，保证爆仓价始终在止损价之外。
