# MACD背离扫描模式设计

## 概述

在现有「底部蓄力」扫描模式基础上，新增「MACD背离」扫描模式，检测日线级别的底背离（bullish divergence）和顶背离（bearish divergence）。两种模式通过 `--mode` 命令行参数切换，互不干扰。

## 背离检测逻辑

### MACD计算

使用标准参数 EMA(12, 26, 9)，基于日K线收盘价计算：
- DIF = EMA12 - EMA26
- DEA = EMA9(DIF)
- MACD柱 = (DIF - DEA) * 2

### 波谷/波峰识别

在最近60根日K线中寻找价格的局部极值点。判定规则：某根K线的收盘价比前后各 `pivot_len`（默认3）根K线都低（高），则为局部波谷（波峰）。

### 底背离判定

取最近两个价格波谷 P1（较早）和 P2（较近）：
- 价格：P2.close < P1.close（价格创新低）
- DIF：P2.dif > P1.dif（DIF未创新低）
- 间距：15 <= P2.index - P1.index <= 60

满足以上三条即为底背离。

### 顶背离判定

取最近两个价格波峰 P1（较早）和 P2（较近）：
- 价格：P2.close > P1.close（价格创新高）
- DIF：P2.dif < P1.dif（DIF未创新高）
- 间距：15 <= P2.index - P1.index <= 60

满足以上三条即为顶背离。

## 数据结构

### DivergenceResult

```python
@dataclass
class DivergenceResult:
    divergence_type: str       # "bullish" | "bearish" | "none"
    price_1: float             # 第一个极值点价格
    price_2: float             # 第二个极值点价格
    dif_1: float               # 第一个极值点DIF值
    dif_2: float               # 第二个极值点DIF值
    pivot_distance: int        # 两极值点间距（K线根数）
    score: float               # 综合评分 [0, 1]
```

## 评分

综合评分 0-1，由三个维度加权：

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| 背离强度 | 0.4 | 价格变化方向与DIF变化方向的偏离程度，归一化到 [0,1] |
| MACD柱确认 | 0.3 | 第二个极值点附近MACD柱是否呈收缩趋势（底背离柱值回升、顶背离柱值回落） |
| 时间合理性 | 0.3 | 两极值点间距越接近30天得分越高，线性衰减 |

## 信号生成

复用现有 `SignalConfig`（min_score / hold_days / stop_loss / take_profit）。

- **底背离**：做多信号 — entry=当前价，stop_loss=entry*(1-sl)，take_profit=entry*(1+tp)
- **顶背离**：做空信号 — entry=当前价，stop_loss=entry*(1+sl)，take_profit=entry*(1-tp)

扩展 `TradeSignal`，增加 `signal_type` 字段（"底背离" / "顶背离"）和 `mode` 字段（"divergence"）。

## CLI集成

```
python main.py                      # 默认底部蓄力模式
python main.py --mode accumulation  # 显式指定底部蓄力
python main.py --mode divergence    # MACD背离模式
```

`--mode` 参数 choices=["accumulation", "divergence"]，默认 "accumulation"。

## K线数据

背离模式需要更多历史数据：90天（60天检测窗口 + 26天MACD预热 + 余量）。复用 `scanner/kline.py` 的 `fetch_klines` 和 `fetch_klines_batch`，传入 `days=90`。

## 输出格式

一张表合并底背离和顶背离，增加「类型」列：

```
排名  币种          类型    价格    评分   入场价   止损价   止盈价   持仓天数
  1   XXX/USDT    底背离  1.2340  0.75  1.2340  1.1723  1.3327       3
  2   YYY/USDT    顶背离  5.6780  0.68  5.6780  5.9619  5.2244       3
```

结果保存到 `results/` 目录，文件名格式 `divergence_{timestamp}.json` 和 `.txt`。

## 数据库跟踪

`scanner/tracker.py` 的 `scan_results` 表增加 `mode` 字段（TEXT，默认 "accumulation"），区分不同扫描模式的记录。现有数据不受影响（默认值兼容）。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scanner/divergence.py` | 新建 | MACD计算、波谷/波峰识别、背离检测、评分 |
| `scanner/signal.py` | 修改 | TradeSignal增加signal_type/mode字段，generate_signals支持背离信号 |
| `scanner/tracker.py` | 修改 | scan_results表增加mode字段 |
| `main.py` | 修改 | 增加--mode参数，新增run_divergence()函数 |
| `tests/test_divergence.py` | 新建 | 背离检测单元测试 |

## 不改动

- 现有底部蓄力检测逻辑（`scanner/detector.py`、`scanner/scorer.py`）
- K线拉取逻辑（`scanner/kline.py`）— 仅传入不同days参数
- 回测模块 — 暂不支持背离模式
