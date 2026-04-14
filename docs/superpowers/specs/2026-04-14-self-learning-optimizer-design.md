# 策略自学习优化器设计

> 日期: 2026-04-14

## 背景

当前系统的 scorer 权重 (0.3/0.25/0.25/0.2)、detector 阈值、signal 门槛均为人工设定，未经数据验证。回测显示：

- Accumulation 模式整体 7d 胜率仅 40%，平均收益 -1.69%
- 分数区分度差：高分档胜率与低分档无显著差异
- Divergence 模式 score≥0.7 的 7d 胜率 54.9%，有一定区分度但仍不够

目标：让系统基于实际收益数据自我校准参数、学习信号质量模式、持续改进。

## 整体架构

在现有管道后叠加三层，不改动现有检测/评分逻辑：

```
现有管道 (detector → scorer → confirmation → signal)
    ↓
[Layer 1] Optuna 参数优化器 — 离线搜索最优权重/阈值
    ↓
[Layer 2] ML 信号过滤器 — LightGBM 二次打分
    ↓
[Layer 3] 反馈闭环 — 自动追踪收益 + 定期重训练
```

新增文件位于 `scanner/optimize/`:

| 文件 | 职责 |
|------|------|
| `__init__.py` | 包初始化 |
| `param_optimizer.py` | Optuna 贝叶斯参数搜索 |
| `feature_engine.py` | 特征提取（信号特征 + 确认层 + 市场环境） |
| `ml_filter.py` | LightGBM 训练与推理 |
| `feedback.py` | 信号结果追踪与收益回填 |
| `retrain.py` | 定期重训练入口 |

## Layer 1：Optuna 参数优化

### 搜索空间

| 参数组 | 参数 | 当前值 | 搜索范围 |
|--------|------|--------|----------|
| scorer 权重 | w_volume, w_drop, w_trend, w_slow | 0.3/0.25/0.25/0.2 | 各 [0.05, 0.6]，归一化为和=1 |
| detector 阈值 | volume_ratio, drop_min, drop_max, max_daily_change | 0.5/0.05/0.15/0.05 | 各 ±50% 浮动 |
| signal 门槛 | min_score | 0.84 | [0.5, 0.95] |
| confirmation | confirmation_min_pass | 4 | [2, 6] |

### 目标函数

```
objective = win_rate_7d × mean_return_7d
```

约束：筛选后样本量 ≥ 10，不足则返回大负数惩罚该 trial。

### 防过拟合

用 `split_hits_by_median_date` 按时间分前半/后半：
- 前半段用于 Optuna 优化
- 后半段用于验证
- 后半段胜率比前半段低超过 15 个百分点时，惩罚该 trial

### 输出

最优参数写入 `config.yaml` 的 `optimized:` 段，运行时自动读取覆盖默认值。

## Layer 2：ML 信号过滤器

### 特征

| 组 | 特征 | 来源 |
|----|------|------|
| 信号特征 | volume_ratio, drop_pct, r_squared, max_daily_pct, window_days, score | DetectionResult + scorer |
| 确认层特征 | rsi, obv_7d, mfi, volume_surge, atr_accel, momentum_5d, confirmation_score | ConfirmationResult.details |
| 市场环境 | btc_return_7d, btc_volatility_14d, total_market_volume_change | BTC K线实时计算 |

> btc_return_7d = BTC 近 7 日收益率；btc_volatility_14d = BTC 近 14 日收盘价标准差 / 均价；total_market_volume_change = 该币种近 3 日均量 / 前 7 日均量（复用 confirmation.compute_volume_surge）。

### Label

信号发出后 7d 收益 > 0 为正样本 (1)，否则为负样本 (0)。

### 训练与验证

- 使用 TimeSeriesSplit（时间序列交叉验证），禁止随机 KFold
- 最少 100 条带 label 样本才启用 ML 层，不足时降级为纯规则引擎

### 推理流程

```
原始 score ≥ min_score 的信号
    → feature_engine.extract() 提取特征向量
    → ml_filter.predict_proba() 输出概率
    → final_score = 0.4 × 原始score + 0.6 × ml_proba
    → final_score ≥ 阈值才输出
```

模型文件保存在 `scanner/optimize/models/`，带时间戳版本管理。

## Layer 3：反馈闭环

### 新增数据库表 signal_outcomes

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| scan_result_id | INTEGER FK | 关联 scan_results.id |
| symbol | TEXT | 币种 |
| signal_date | TEXT | 信号发出日期 |
| signal_price | REAL | 信号发出时价格 |
| return_3d | REAL | 3 天后收益率（NULL=未到期） |
| return_7d | REAL | 7 天后收益率 |
| return_14d | REAL | 14 天后收益率 |
| return_30d | REAL | 30 天后收益率 |
| features_json | TEXT | 信号发出时的完整特征向量快照 (JSON) |
| btc_price | REAL | 信号发出时 BTC 价格 |
| collected_at | TEXT | 最后一次回填时间 |

### 回填逻辑 (feedback.py)

- 扫描 signal_outcomes 中 return 列为 NULL 且已到期的记录
- 拉取该币种最新 K 线，计算实际收益率
- 批量 UPDATE 回填
- 每次 main.py 扫描完成后自动调用 `feedback.collect()`

### 重训练逻辑 (retrain.py)

1. 检查 signal_outcomes 中 return_7d 非 NULL 的记录数
2. ≥ 100 条时触发 LightGBM 重训练
3. 用最近 20% 数据做验证，胜率提升才替换旧模型
4. 同时跑一轮 Optuna（50 trials）看参数是否需要更新
5. 输出训练报告到 `results/retrain_YYYY-MM-DD.json`

## CLI 入口

```bash
.venv/bin/python main.py --optimize          # 跑 Optuna 参数优化（需要先有回测数据）
.venv/bin/python main.py --retrain           # 收集反馈 + 重训练 ML 模型
.venv/bin/python main.py --optimize-report   # 查看当前最优参数 & 模型表现
```

## 依赖

新增 pip 包：
- `optuna` — 贝叶斯超参搜索
- `lightgbm` — 梯度提升树
- `scikit-learn` — TimeSeriesSplit、metrics

## 测试策略

- 单元测试：feature_engine 特征提取、feedback 回填逻辑、param_optimizer 目标函数计算
- 集成测试：完整的"回测 → 优化 → 验证"流程（用合成数据）
- 防过拟合验证：确保后半段胜率不崩塌
