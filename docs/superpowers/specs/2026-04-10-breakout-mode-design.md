# 天量回踩二攻模式设计（--mode breakout）

## 背景

MACD 背离模式命中率过高（122/371 = 33%），大部分推荐币种仅小幅波动。真正大涨的 ONG（+17.5%）和 BLUR（+13.4%）共享同一特征：天量拉升 → 缩量回调 → 放量二攻。此模式与"底部反转"本质不同，属于"强势回调买入"策略，需独立模式捕捉。

## 核心概念

| 术语 | 定义 |
|------|------|
| 天量日 | 单日成交量 >= 前 20 日均量 × 5 |
| 缩量回调 | 天量日后 3-7 天内，成交量萎缩至天量日的 30% 以下 |
| 放量二攻 | 缩量阶段后某日成交量 >= 近 3 日均量 × 2 |
| 信号新鲜度 | 二攻日必须在最近 3 个交易日内 |

## 案例验证

### ONG/USDT（成功）

```
4/3  天量 192M（前20日均量的 ~11x）→ +47.1%
4/5-4/8 缩量至 16M-27M（天量的 8%-14%）
4/9  放量二攻 68M（近3日均量 20M 的 3.4x）→ +17.5%
```

- 天量倍数 11x → 高分
- 缩量至 8%-14% → 高分（抛压充分释放）
- 二攻力度 3.4x → 中高分
- 二攻日 4/9 在最近 3 天内 → 新鲜

### BLUR/USDT（成功）

```
4/1  天量 898M（前20日均量的 ~158x）→ +33.3%
4/3-4/7 缩量至 19M-90M（天量的 2%-10%）
4/8  放量二攻 190M（近3日均量 21M 的 9x）→ +4.9%
4/9  继续放量 539M → +13.4%
```

- 天量倍数 158x → 满分
- 缩量至 2% → 满分
- 二攻力度 9x → 高分

### FIDA/USDT（正确排除）

```
4/2  天量 1292M → +28.7%
4/3-4/9 缩量至 81M-695M（天量的 5%-54%）
无放量二攻 → 不命中
```

- 虽然有天量和缩量，但没有放量二攻，不产出信号

## 检测流程

```
全部币种 K线(30天)
  → Step 1: 扫描天量日（单日量 >= 20日均量 × 5）
  → Step 2: 天量日后是否有缩量回调（连续 N 天量 < 天量日 × 0.3）
  → Step 3: 缩量后是否出现放量二攻（某日量 >= 近3日均量 × 2）
  → Step 4: 二攻日在最近 3 个交易日内（信号新鲜）
  → 命中 → 评分 → 确认层过滤 + 加分 → 信号输出
```

### 检测函数签名

```python
@dataclass
class BreakoutResult:
    matched: bool
    spike_date: str          # 天量日日期
    spike_volume_ratio: float  # 天量倍数（相对20日均量）
    spike_high: float        # 天量日最高价
    pullback_low: float      # 回调阶段最低价
    pullback_shrink: float   # 缩量程度（最低量/天量）
    reattack_date: str       # 二攻日日期
    reattack_volume_ratio: float  # 二攻量/近3日均量
    reattack_close: float    # 二攻日收盘价
    days_since_spike: int    # 天量日距今天数
    score: float             # 综合评分 [0, 1]


def detect_breakout(
    df: pd.DataFrame,
    spike_multiplier: float = 5.0,
    shrink_threshold: float = 0.3,
    reattack_multiplier: float = 2.0,
    max_pullback_days: int = 10,
    freshness_days: int = 3,
) -> BreakoutResult:
```

参数说明：
- `spike_multiplier`: 天量倍数阈值，默认 5x
- `shrink_threshold`: 缩量阈值，量需低于天量的 30%
- `reattack_multiplier`: 二攻量需 >= 近 3 日均量 × 2
- `max_pullback_days`: 天量后最多等多少天出现二攻
- `freshness_days`: 二攻日必须在最近 N 个交易日内

### 多次天量处理

若一个币在 30 天内出现多次天量日，取最近一次。若最近一次天量后尚未二攻，不命中。

## 评分公式

```python
score = (
    spike_score * 0.3 +       # 天量倍数
    shrink_score * 0.2 +       # 缩量质量
    reattack_score * 0.3 +     # 二攻力度
    position_score * 0.2       # 价格位置
)
```

### 各分项计算

**天量倍数分（0.3）：**
```python
# 对数缩放：5x=0.3, 10x=0.6, 20x=0.85, 50x+=1.0
spike_score = min(1.0, math.log(spike_volume_ratio / 5.0 + 1) / math.log(11))
```

**缩量质量分（0.2）：**
```python
# 缩到天量的 10% 以下=1.0, 30%=0.5, 50%+=0
shrink_score = max(0.0, 1.0 - pullback_shrink / 0.5)
```
其中 `pullback_shrink` = 回调期间最低日量 / 天量日量。

**二攻力度分（0.3）：**
```python
# 2x=0.3, 5x=0.7, 10x+=1.0
reattack_score = min(1.0, math.log(reattack_volume_ratio / 2.0 + 1) / math.log(6))
```

**价格位置分（0.2）：**
```python
# 二攻收盘 vs 天量日高点，越接近越强
position_score = min(1.0, reattack_close / spike_high)
```

收盘价 = 天量高点 → 1.0（突破），收盘 = 高点的 50% → 0.5（半腰）。

## 信号生成

| 字段 | 计算 |
|------|------|
| 入场价 | 二攻日收盘价 |
| 止损价 | 缩量回调阶段最低价 × 0.97（最低价下方 3%） |
| 止盈价 | 天量日最高价（前高回测） |
| 信号类型 | "天量回踩" |
| 持仓天数 | 由 config 控制，默认 3 天 |

## 与现有系统的关系

### 复用

| 模块 | 说明 |
|------|------|
| `scanner/kline.py` | K线数据获取，不改 |
| `scanner/signal.py` | SignalConfig + TradeSignal + generate_signals，不改 |
| `scanner/confirmation.py` | 确认层过滤 + 加分，直接复用 |
| `scanner/tracker.py` | save_scan 记录，mode="breakout" |
| `scanner/coingecko.py` | 市值过滤，不改 |

### 新增

| 文件 | 职责 |
|------|------|
| `scanner/breakout.py` | `BreakoutResult` + `detect_breakout()` + `score_breakout()` |
| `tests/test_breakout.py` | breakout 模块测试 |

### 改动

| 文件 | 改动 |
|------|------|
| `main.py` | 新增 `run_breakout()` 函数 + argparse `--mode breakout` |
| `config.yaml` | 新增 `breakout:` 配置段 |

## config.yaml 新增

```yaml
breakout:
  spike_multiplier: 5.0       # 天量倍数阈值
  shrink_threshold: 0.3       # 缩量需低于天量的 30%
  reattack_multiplier: 2.0    # 二攻量 >= 近3日均量 × 2
  max_pullback_days: 10       # 天量后最多等10天
  freshness_days: 3           # 二攻日必须在最近3天内
  top_n: 20
```

## CLI

```bash
.venv/bin/python main.py --mode breakout              # 天量回踩二攻扫描
.venv/bin/python main.py --mode breakout --no-confirm  # 关闭确认层
```

## 不做的事

- 不改现有 divergence 模式（保持独立）
- 不加 BTC 相关性过滤（天量本身隐含独立行情判断）
- 不加回测支持（先验证实盘效果，后续迭代加）
- 不改背离命中数过多的问题（由新模式绕过）
