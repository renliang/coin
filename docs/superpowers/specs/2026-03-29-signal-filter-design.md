# 信号过滤 + 交易建议设计

## 目标

基于回测结论，对扫描结果增加信号过滤（score 门槛）和交易建议（入场/止损/止盈/持仓天数），提升扫描器的实战可用性。

## 回测依据

- 高分组（score ≥ 0.6）3 天胜率 69%，平均收益 +4.15%
- 低分组 3 天胜率仅 48%，平均收益 -0.88%
- 所有分组 14/30 天收益为负，只适合短线

## 配置

在 `config.yaml` 新增 `signal` 段：

```yaml
signal:
  min_score: 0.6        # 最低评分门槛
  hold_days: 3          # 建议持仓天数
  stop_loss: 0.05       # 止损比例 5%
  take_profit: 0.08     # 止盈比例 8%
```

所有参数有默认值，不配置时使用上述默认。

## 模块设计

### `scanner/signal.py`（新建）

```python
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
    entry_price: float      # = price
    stop_loss_price: float  # = price * (1 - stop_loss)
    take_profit_price: float  # = price * (1 + take_profit)
    hold_days: int

def generate_signals(
    matches: list[dict],
    signal_config: SignalConfig,
) -> list[TradeSignal]:
    """过滤低分结果，为通过的结果生成交易建议。"""
```

### `main.py` 改动

- `load_config()` 读取 `signal` 段，构造 `SignalConfig`
- `run()` 中在 `rank_results` 后调用 `generate_signals()` 过滤
- 替换输出表格，新增止损价/止盈价/持仓天数列
- JSON 输出也包含交易建议字段

### 输出表格

```
排名  币种        价格    评分  入场价   止损价   止盈价   持仓天数
  1  XXX/USDT  0.0046  0.63  0.0046  0.00437  0.00497     3
```

## 测试

### `tests/test_signal.py`（新建）

- 测试 score 过滤：低于 min_score 的被过滤
- 测试交易参数计算：止损价 = price * 0.95，止盈价 = price * 1.08
- 测试空输入和全部被过滤的情况

## 不做的事

- 不修改 detector/scorer/backtest
- 不接入交易所 API
- 不做自动下单
