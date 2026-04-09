# 背离信号评分优化设计

## 背景

2026-04-09 背离扫描结果中，FIDA/USDT（0.87分）排名高于 ONG/USDT（0.85分），但次日 ONG 涨 17% 而 FIDA 继续横盘。分析发现：

- FIDA 高分来源于时间合理性（0.9333），背离强度仅 0.5855
- ONG 背离强度更优（0.5942），但时间分较低（0.8667）拖累总分
- 确认层为及格制（pass/fail），无法区分"即将启动"与"继续横盘"

**核心问题：** 评分体系过度重视时间周期巧合，轻视动能强度；确认层缺少启动前兆指标且无法参与排名。

## 改动范围

| 文件 | 改动 |
|------|------|
| `scanner/divergence.py` | `_score_divergence()` 权重调整 |
| `scanner/confirmation.py` | 新增 2 个指标函数 + `confirm_signal()` 返回连续分 |
| `scanner/signal.py` | `SignalConfig` 新增字段 |
| `main.py` | 加分逻辑集成 + 输出格式更新 |
| `scanner/backtest.py` | 支持新评分 |
| `tests/test_confirmation.py` | 新增指标测试 |
| `tests/test_divergence.py` | 权重变更后的分数断言更新 |

## 改动一：背离评分权重调优

**文件：** `scanner/divergence.py:74`

**现状：**

```python
return strength * 0.4 + confirm * 0.3 + time_score * 0.3
```

三个分项中，strength(0.4) + confirm(0.3) = 0.7 为动能相关，time_score(0.3) 为时间相关。

**改为：**

```python
return strength * 0.5 + confirm * 0.3 + time_score * 0.2
```

动能占比从 0.7 提升到 0.8，时间合理性从 0.3 降到 0.2。

**效果预估：**
- FIDA: 0.5855×0.5 + confirm×0.3 + 0.9333×0.2（时间贡献从 0.28 降到 0.19）
- ONG: 0.5942×0.5 + confirm×0.3 + 0.8667×0.2（strength 贡献从 0.24 升到 0.30）
- ONG 基础分将反超 FIDA

## 改动二：新增启动前兆指标

**文件：** `scanner/confirmation.py`

### 2a. 成交量突变 `compute_volume_surge`

检测近期是否出现放量，暗示资金开始进场。

```python
def compute_volume_surge(volumes: pd.Series, recent_days: int = 3, baseline_days: int = 7) -> float:
    """计算近 recent_days 日均量 / 前 baseline_days 日均量。"""
    if len(volumes) < recent_days + baseline_days:
        return 1.0
    recent_avg = volumes.iloc[-recent_days:].mean()
    baseline_avg = volumes.iloc[-(recent_days + baseline_days):-recent_days].mean()
    if baseline_avg == 0:
        return 1.0
    return float(recent_avg / baseline_avg)
```

- 返回值：比值（1.0 = 无变化，1.5 = 放量 50%，2.0 = 倍量）
- 参数：近 3 日 vs 前 7 日

### 2b. 波动率加速 `compute_atr_accel`

检测波动率是否在扩大，暗示行情即将突破盘整。

```python
def compute_atr_accel(
    highs: pd.Series, lows: pd.Series, closes: pd.Series,
    recent_days: int = 7, baseline_days: int = 14,
) -> float:
    """计算近 recent_days ATR / 前 baseline_days ATR。"""
    def _atr(h, l, c):
        tr = pd.concat([
            h - l,
            (h - c.shift(1)).abs(),
            (l - c.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.mean()

    if len(closes) < recent_days + baseline_days + 1:
        return 1.0
    recent_atr = _atr(
        highs.iloc[-recent_days:], lows.iloc[-recent_days:], closes.iloc[-(recent_days + 1):],
    )
    baseline_atr = _atr(
        highs.iloc[-(recent_days + baseline_days):-recent_days],
        lows.iloc[-(recent_days + baseline_days):-recent_days],
        closes.iloc[-(recent_days + baseline_days + 1):-recent_days],
    )
    if baseline_atr == 0:
        return 1.0
    return float(recent_atr / baseline_atr)
```

- 返回值：ATR 比值（1.0 = 无变化，1.2 = 加速 20%）
- 参数：近 7 日 vs 前 14 日

## 改动三：确认层从及格制改为加分制

**文件：** `scanner/confirmation.py`

### 3a. ConfirmationResult 扩展

```python
@dataclass
class ConfirmationResult:
    passed: bool           # 是否通过过滤（兼容现有逻辑）
    passed_count: int      # 通过项数（兼容）
    score: float           # 新增：确认层连续得分 [0, 1]
    bonus: float           # 新增：加分值 [-0.10, +0.10]
    rsi_ok: bool
    obv_ok: bool
    volume_ratio_ok: bool
    mfi_ok: bool
    volume_surge_ok: bool  # 新增
    atr_accel_ok: bool     # 新增
    details: dict
```

### 3b. 6 项指标评分逻辑

每项指标从 bool 改为 0-1 连续分，同时保留 bool 用于过滤判断。

**现有 4 项改为连续分（long 方向）：**

| 指标 | bool 条件（不变） | 连续分计算 |
|------|------------------|-----------|
| RSI | 30 ≤ rsi ≤ 70 | `1.0 - abs(rsi - 50) / 50`，距中心越近越好 |
| OBV | obv_trend > 0 | `min(1.0, max(0.0, obv_trend / abs(total_obv) * 10))` 归一化 |
| 量比 | vol_ratio ≥ 1.0 | `min(1.0, vol_ratio / 2.0)`，2x 满分 |
| MFI | 20 ≤ mfi ≤ 80 | `1.0 - abs(mfi - 50) / 50`，距中心越近越好 |

**新增 2 项：**

| 指标 | bool 条件 | 连续分计算 |
|------|----------|-----------|
| volume_surge | surge ≥ 1.5 | `min(1.0, max(0.0, (surge - 1.0) / 1.0))`，2x 满分 |
| atr_accel | accel > 1.2 | `min(1.0, max(0.0, (accel - 1.0) / 0.5))`，1.5x 满分 |

**short 方向差异：** OBV 和量比条件取反（OBV < 0，量比 ≤ 1.0），连续分用 `1.0 - score` 镜像。

### 3c. 确认层得分与加分计算

```python
# 6 项均分
confirmation_score = mean(rsi_score, obv_score, vol_ratio_score, mfi_score, volume_surge_score, atr_accel_score)

# 过滤判断（兼容现有逻辑）：6 项 bool 中至少 N 项通过
passed = sum([rsi_ok, obv_ok, volume_ratio_ok, mfi_ok, volume_surge_ok, atr_accel_ok]) >= min_pass

# 加分：以 0.5 为中性点，最大 ±0.10
bonus = (confirmation_score - 0.5) * 0.2
bonus = max(-0.10, min(0.10, bonus))
```

### 3d. 过滤阈值调整

原来 4 项中通过 3 项，现在 6 项：

- `confirmation_min_pass` 默认从 3 改为 4（6 项中至少 4 项）
- config.yaml 中同步更新

## 改动四：最终排名公式

**文件：** `main.py` — `run_divergence()` 和 `run()`

```python
# 在确认层过滤之后、generate_signals() 之前
for m in ranked:
    m["base_score"] = m["score"]          # 保存原始背离分
    m["confirm_bonus"] = result.bonus      # 确认层加分
    m["score"] = m["base_score"] + result.bonus  # 最终分
```

**输出格式更新：** 表格新增 `加分` 列，示例：

```
排名  币种         类型    价格    基础分  加分    总分
  1  ONG/USDT   底背离  0.0751  0.85  +0.06  0.91
  2  FIDA/USDT  底背离  0.0162  0.87  -0.02  0.85
```

## 改动五：backtest.py 适配

**文件：** `scanner/backtest.py`

回测中 `confirm_signal()` 返回新的 `ConfirmationResult`（含 bonus），加分逻辑与 main.py 一致：

```python
if confirmation:
    conf = confirm_signal(slice_df, "long", confirmation_min_pass)
    if not conf.passed:
        continue
    hit.score = hit.score + conf.bonus
```

## 兼容性

- `--no-confirm` 仍然有效：跳过确认层过滤和加分
- config.yaml `confirmation: false` 同理
- 旧的 4 项 bool 字段保留，新增 2 项
- `confirmation_min_pass` 默认值变更（3→4），但 config.yaml 显式配置优先

## 案例验证预期

基于 2026-04-09 数据，优化后：

| 币种 | 背离基础分（新权重） | 确认加分 | 最终分 | 预期排名变化 |
|------|---------------------|---------|--------|-------------|
| ONG | ~0.85（strength 提升） | +0.05~0.07（若成交量突变） | ~0.91 | 上升 |
| FIDA | ~0.84（time 权重降低） | ~0.00（无成交量突变） | ~0.84 | 下降 |
| VIC | ~0.85 | -0.05~-0.08（OBV 流出+量比差） | ~0.78 | 被过滤或低排名 |
