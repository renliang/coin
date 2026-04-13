# 信号确认层设计

## 背景

当前系统的蓄力模式和 MACD 背离模式能检测出候选信号，但存在**假信号**问题——方向判断错误。典型案例：VIC/USDT 背离评分 0.88（排名第一），但 OBV 净流出、涨跌日量比 0.75x（空头主导），实际资金面与信号方向矛盾。

## 目标

在现有检测-评分流程之后，增加一个**后置确认层**，通过多指标共振 + 量价验证过滤假信号，提升方向准确率。

## 设计原则

- **纯增量**：不改动 `detector.py`、`scorer.py`、`divergence.py` 的现有逻辑
- **可开关**：通过 config 和 CLI 参数控制，方便对比效果
- **宽松阈值**：4 项中允许 1 项不达标（至少 3/4 通过），避免过度过滤

## 架构

```
现有流程:  检测 → 评分 → generate_signals() → 输出
新流程:    检测 → 评分 → confirm_signal() → generate_signals() → 输出
                          ↑
                    scanner/confirmation.py (新增)
```

## 新增文件

### scanner/confirmation.py

#### 数据结构

```python
@dataclass
class ConfirmationResult:
    passed: bool              # 是否通过确认
    rsi_ok: bool              # RSI 检查
    obv_ok: bool              # OBV 趋势检查
    volume_ratio_ok: bool     # 涨跌日量比检查
    mfi_ok: bool              # MFI 检查
    passed_count: int         # 通过项数 (0-4)
    details: dict             # 各指标实际数值
```

#### 核心函数

```python
def confirm_signal(
    df: pd.DataFrame,
    direction: str,            # "long" | "short"
    min_pass: int = 3,         # 至少通过几项
) -> ConfirmationResult
```

#### 4 项确认指标

**做多信号 (direction="long")**:

| 指标 | 计算 | 通过条件 | 拦截目标 |
|------|------|---------|---------|
| RSI(14) | 标准 RSI | 30 ≤ RSI ≤ 70 | 已超买的假底 |
| OBV 7d | 近7日 OBV 净变化 | > 0 (净流入) | 价格见底但资金在跑 |
| 涨跌日量比 | 近7日上涨日总量 / 下跌日总量 | ≥ 1.0 | 空头主导的反弹 |
| MFI(14) | 资金流量指标 | 20 ≤ MFI ≤ 80 | 极端超买/超卖 |

**做空信号 (direction="short")**:

| 指标 | 通过条件 |
|------|---------|
| RSI(14) | 30 ≤ RSI ≤ 70 |
| OBV 7d | < 0 (净流出) |
| 涨跌日量比 | ≤ 1.0 (空头主导) |
| MFI(14) | 20 ≤ MFI ≤ 80 |

#### 辅助计算函数

```python
def compute_rsi(closes: pd.Series, period: int = 14) -> float
def compute_obv_trend(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float
def compute_up_down_volume_ratio(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float
def compute_mfi(highs: pd.Series, lows: pd.Series, closes: pd.Series, volumes: pd.Series, period: int = 14) -> float
```

## 案例验证

基于 2026-04-08 实际数据的验证结果：

| 币种 | RSI | OBV 7d | 量比 | MFI | 通过数 | 结果 |
|------|-----|--------|------|-----|--------|------|
| FIDA | 57.3 OK | +10.8亿 OK | 2.03x OK | 65.8 OK | 4/4 **通过** |
| SOLV | 57.5 OK | +93.8亿 OK | 2.93x OK | 77.9 OK | 4/4 **通过** |
| VIC | 61.2 OK | -2940万 NG | 0.75x NG | 78.8 OK | 2/4 **过滤** |

VIC 被正确过滤（资金流出 + 空头主导），FIDA 和 SOLV 正确保留。

## 集成改动

### config.yaml 新增字段

```yaml
signal:
  min_score: 0.6
  confirmation: true            # 是否启用确认层
  confirmation_min_pass: 3      # 4项中至少通过几项
```

### CLI 新增参数

- `--no-confirm`: 临时关闭确认层

### main.py 改动

在 `run()` 和 `run_divergence()` 中，`generate_signals()` 之前插入确认过滤：

```python
if confirmation_enabled:
    confirmed = []
    filtered_symbols = []
    for m in matches:
        direction = "short" if m.get("signal_type") == "顶背离" else "long"
        result = confirm_signal(klines[m["symbol"]], direction, min_pass)
        if result.passed:
            confirmed.append(m)
        else:
            filtered_symbols.append(m["symbol"])
    print(f"[确认] {len(matches)} -> {len(confirmed)} 个 (过滤{len(filtered_symbols)}个: {', '.join(filtered_symbols[:5])})")
    matches = confirmed
```

### backtest.py 改动

`run_backtest()` 新增可选参数 `confirmation=True`，在每个历史命中点同样跑确认层，这样可以对比：
- 无确认层的历史胜率
- 有确认层的历史胜率

## 不改动的文件

- `scanner/detector.py` — 检测逻辑不变
- `scanner/scorer.py` — 评分权重不变
- `scanner/divergence.py` — 背离算法不变
- `scanner/signal.py` — 信号生成逻辑不变

## 测试计划

1. 单元测试 `test_confirmation.py`：构造 DataFrame 验证每个指标计算正确
2. 集成测试：跑 `--mode divergence` 对比开/关确认层的信号差异
3. 回测验证：跑 180 天历史数据，对比确认层开/关的胜率变化
