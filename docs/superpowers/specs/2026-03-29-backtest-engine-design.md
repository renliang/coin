# 回测引擎设计：底部蓄力形态有效性验证

## 目标

验证 scanner 检测到的"底部蓄力"形态是否真的预示上涨。通过对历史 K 线做滑动窗口回扫，统计形态命中后 N 天的收益率，评估形态的预测能力和评分系统的区分度。

## 方案：滑动窗口全量回扫

对每个币种拉取 180 天日线 K 线，逐日运行 `detect_pattern()`，记录所有命中形态并计算后续收益。

## 架构

新增模块 `scanner/backtest.py`，复用现有 `detector`、`scorer`、`kline` 模块，不修改它们的接口。

```
main.py --backtest
    ↓
scanner/kline.py (拉180天K线)
    ↓
scanner/backtest.py (滑动窗口检测 + 收益计算 + 统计)
    ↓
终端表格 + results/backtest_*.json
```

## 核心逻辑

### 1. 数据获取

复用 `fetch_klines_batch(symbols, days=180)`，从 Binance 拉取每个币种 180 天日线。币种来源与当前扫描一致（OKX 合约 ∩ Binance 现货），也支持 `--symbols` 手动指定。

### 2. 滑动窗口回扫

对每个币种的 K 线 DataFrame：

- 从第 `window_max_days` 行开始，逐日向后滑动
- 每个位置 `i`，截取 `df[0:i]` 交给 `detect_pattern()`（它自动取 tail）
- 若 `matched=True`，记录一条命中记录
- **去重规则**：同一币种，如果上一次命中距当前不足 `window_max_days` 天，跳过（避免同一段下跌反复计数）

命中记录包含：
```python
{
    "symbol": str,
    "detect_date": str,       # 检测日（K线截止日）
    "window_days": int,
    "drop_pct": float,
    "volume_ratio": float,
    "score": float,
    "returns": {
        "3d": float | None,   # 3天后收益率
        "7d": float | None,
        "14d": float | None,
        "30d": float | None,
    }
}
```

### 3. 收益计算

检测日为 K 线截止日（索引 `i-1`），其收盘价为基准价 `base_price`。

```
return_Nd = (close[i-1+N] - base_price) / base_price
```

数据不足 N 天时标记为 `None`，不参与统计。

### 4. 统计汇总

#### 整体统计（按周期 3/7/14/30d）

| 指标 | 说明 |
|------|------|
| 样本数 | 有效收益数据的命中次数 |
| 胜率 | 收益 > 0 的比例 |
| 平均收益 | mean |
| 中位数收益 | median |
| 最大收益 | max |
| 最大亏损 | min |

#### 按 score 分档

| 分档 | 范围 |
|------|------|
| 高分 | score >= 0.6 |
| 中分 | 0.4 <= score < 0.6 |
| 低分 | score < 0.4 |

每档分别输出上述指标，验证评分是否能区分形态质量。

### 5. 输出

**终端输出：**
- 整体统计表格
- 分档统计表格
- 总命中数 / 总币种数概要

**文件输出：**
- `results/backtest_YYYY-MM-DD_HHMMSS.json`：包含所有命中记录和统计结果
- `results/backtest_YYYY-MM-DD_HHMMSS.txt`：终端输出的文本版

### 6. CLI 接口

在 `main.py` 新增参数：

```
python main.py --backtest                    # 全量回测
python main.py --backtest --symbols BTC/USDT ETH/USDT  # 指定币种
python main.py --backtest --days 365         # 自定义历史天数
```

参数：
- `--backtest`：触发回测模式
- `--days`：历史 K 线天数，默认 180
- `--symbols`：与现有参数复用
- 检测参数从 `config.yaml` 的 `scanner` 段读取，与实时扫描一致

## 模块接口

### `scanner/backtest.py`

```python
@dataclass
class BacktestHit:
    symbol: str
    detect_date: str
    window_days: int
    drop_pct: float
    volume_ratio: float
    score: float
    returns: dict[str, float | None]  # {"3d": ..., "7d": ..., "14d": ..., "30d": ...}

def run_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
) -> list[BacktestHit]:
    """对所有币种做滑动窗口回扫，返回命中列表。"""

def compute_stats(
    hits: list[BacktestHit],
) -> dict:
    """计算整体统计和分档统计。"""

def format_stats(stats: dict) -> str:
    """格式化统计结果为终端表格字符串。"""
```

## 测试

- `tests/test_backtest.py`
- 用合成 K 线数据测试：构造一个明确命中形态的序列 + 后续上涨/下跌，验证命中检测和收益计算
- 测试去重逻辑：连续命中只保留第一次
- 测试统计计算：胜率、平均收益等

## 不做的事

- 不模拟交易（无仓位、止盈止损）
- 不修改现有 detector/scorer 接口
- 不引入新依赖
