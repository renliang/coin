# 币圈全流程扩展：舆情分析 + 多策略组合管理

> 日期：2026-04-16
> 状态：设计阶段

## 1. 目标

在现有 `coin` 项目上渐进扩展两个核心模块：

1. **舆情分析（sentiment/）** — 多源数据采集 + NLP 情绪打分，输出统一情绪信号融入现有扫描评分
2. **多策略组合管理（portfolio/）** — 自动化资金分配、风控、再平衡、绩效追踪

部署目标：全云端，远程监控。

## 2. 整体架构

```
coin/
├── scanner/           # 现有 — 行情扫描 + 信号检测
├── sentiment/         # 【新增】舆情采集 + 情绪分析
│   ├── sources/       #   数据源适配器
│   │   ├── twitter.py
│   │   ├── telegram.py
│   │   ├── news.py
│   │   └── onchain.py
│   ├── analyzer.py    #   NLP 情绪打分
│   └── aggregator.py  #   多源融合 → 统一情绪信号
├── portfolio/         # 【新增】多策略组合管理
│   ├── allocator.py   #   策略权重分配
│   ├── risk.py        #   VaR/回撤控制
│   ├── rebalancer.py  #   自动再平衡
│   └── tracker.py     #   组合级绩效追踪
├── cli/               # 现有 — 扩展新子命令
├── main.py            # 现有 — 扩展新入口函数
└── config.yaml        # 现有 — 扩展 sentiment/portfolio 配置段
```

### 核心数据流

```
扫描 → 评分 ──┐
               ├→ 组合管理器 → 仓位分配 → 交易
舆情 → 情绪分 ─┘
```

舆情模块输出情绪信号（[-1, 1] 分值 + 方向），作为加权因子注入评分流程，不替代现有逻辑。

## 3. 舆情模块（sentiment/）

### 3.1 统一数据模型

```python
@dataclass(frozen=True)
class SentimentItem:
    source: str          # "twitter" / "telegram" / "news" / "onchain"
    symbol: str          # "BTC/USDT" 或 ""（全局情绪）
    score: float         # [-1, 1]  负=恐慌  正=贪婪
    confidence: float    # [0, 1]   数据可信度
    raw_text: str        # 原始内容
    timestamp: datetime
```

### 3.2 数据源

| 源 | 工具 | 采集方式 | 频率 | 免费额度 |
|---|------|---------|------|---------|
| Twitter/X | snscrape（无需 API key） | 按币种关键词 + KOL 列表抓取 | 每 30 分钟 | ~1 req/s |
| Telegram | Telethon（需个人账号） | 监听指定频道/群组的消息 | 实时推送 | 自托管，3-5 req/s |
| 新闻 | CryptoPanic API + RSS | 聚合新闻标题 + 摘要 | 每 15 分钟 | 100 次/天 |
| 链上 | Etherscan/Solscan 免费 API | 监控大额转账（>$1M） | 每 5 分钟 | 5 次/秒 |

每个数据源实现统一的 `fetch() -> list[SentimentItem]` 接口。任一数据源失败不影响其他源。

### 3.3 情绪分析器（analyzer.py）

两层方案，按成本递进：

1. **基础层（免费）：** VADER + 加密货币词典扩展（如 "moon"=+0.8, "rug"=-0.9），处理英文推文和新闻
2. **增强层（可选）：** 调用 LLM API（Claude/GPT）对复杂文本做情绪判断，仅在 confidence 低于阈值时触发

链上数据走规则引擎，不走 NLP：
- 大额流入交易所 → 看空信号
- 大额流出交易所 → 看多信号
- 巨鲸新建仓 → 看多

### 3.4 多源融合（aggregator.py）

```
最终情绪分 = w_twitter * twitter_score
           + w_telegram * telegram_score
           + w_news * news_score
           + w_onchain * onchain_score
```

默认权重：Twitter 0.3 / Telegram 0.2 / News 0.3 / Onchain 0.2（config.yaml 可配）。

输出 `SentimentSignal`：
- `score`：[-1, 1] 综合情绪分
- `direction`："bullish" / "bearish" / "neutral"
- `confidence`：加权平均可信度
- 按币种聚合（有具体币种数据时）或全局（无数据时降级）

### 3.5 与现有扫描的集成

情绪分不改变现有 scanner 评分逻辑，在信号生成阶段作为加权因子：

```
adjusted_score = scanner_score * (1 + sentiment_boost)
# sentiment_boost ∈ [-0.2, +0.2]，即最多影响 ±20%
```

即使舆情模块挂了或数据缺失，系统仍能正常运行（降级为 boost=0）。

## 4. 多策略组合管理（portfolio/）

### 4.1 策略注册

现有 3 个扫描模式 + 舆情信号 = 4 个信号源，统一管理：

```python
@dataclass(frozen=True)
class StrategyResult:
    strategy_id: str       # "accumulation" / "divergence" / "breakout" / "sentiment_only"
    signals: list[TradeSignal]
    sharpe: float          # 近 N 天的夏普率
    win_rate: float        # 近 N 天的胜率
    max_drawdown: float    # 近 N 天最大回撤
    correlation: dict[str, float]  # 与其他策略的相关系数
```

### 4.2 资金分配器（allocator.py）

采用 Riskfolio-Lib 做均值-CVaR 优化：

- **输入：** 各策略近 90 天每日收益率
- **输出：** 策略权重字典，如 `{"accumulation": 0.25, "divergence": 0.40, "breakout": 0.20, "sentiment_only": 0.15}`

约束条件：
- 单策略权重上限 50%
- 单策略权重下限 5%
- 夏普率 < 0 的策略权重强制降为下限
- 总仓位上限由 config.yaml 控制（如总资金的 80%）

### 4.3 风控模块（risk.py）

三层风控：

| 层级 | 规则 | 动作 |
|------|------|------|
| 仓位级 | 单仓亏损 > max_stop_loss | 触发止损（现有逻辑） |
| 策略级 | 单策略当日亏损 > 3% | 暂停该策略新开仓 |
| 组合级 | 总组合回撤 > 5% | 全部暂停开仓，仅保留平仓 |

回撤计算基于高水位线，SQLite 持久化每日净值曲线。

### 4.4 自动再平衡（rebalancer.py）

- **触发条件：** 每周一次 或 实际权重偏离目标 > 20%
- **执行方式：** 重新计算最优权重 → 调整各策略可用资金 → 不强制平仓，通过控制新开仓逐步收敛
- 再平衡结果写入 SQLite

### 4.5 绩效追踪（tracker.py）

用 QuantStats 生成报告，扩展现有 scanner/stats.py：

- 每个策略：收益率曲线、夏普、胜率、最大回撤
- 组合级别：加权合成曲线、策略间相关性矩阵
- 输出 HTML 报告到 results/portfolio_report.html

## 5. CLI 扩展

```bash
# 舆情相关
coin sentiment scan            # 手动触发舆情采集
coin sentiment status          # 查看当前情绪指标

# 组合管理
coin portfolio status          # 查看当前各策略权重 + 资金分配
coin portfolio rebalance       # 手动触发再平衡
coin portfolio report          # 生成组合绩效报告
```

## 6. serve 模式扩展

常驻模式增加定时任务：

```
08:10  扫描信号（现有）
*/15   舆情采集（新增）
*/60   刷新信号价格 + 生命周期检查（现有）
每周一  组合再平衡（新增）
```

## 7. config.yaml 新增配置段

```yaml
sentiment:
  enabled: true
  weights:
    twitter: 0.3
    telegram: 0.2
    news: 0.3
    onchain: 0.2
  boost_range: 0.2          # 情绪对评分的最大影响幅度
  vader_threshold: 0.5      # 低于此 confidence 触发 LLM
  llm_enabled: false        # 是否启用 LLM 增强层
  twitter:
    keywords: ["BTC", "ETH", "crypto"]
    kol_list: []            # Twitter 用户名列表
    interval_minutes: 30
  telegram:
    channels: []            # 频道/群组 ID
    api_id_env: "TELEGRAM_API_ID"
    api_hash_env: "TELEGRAM_API_HASH"
  news:
    cryptopanic_api_key_env: "CRYPTOPANIC_API_KEY"
    interval_minutes: 15
  onchain:
    etherscan_api_key_env: "ETHERSCAN_API_KEY"
    min_transfer_usd: 1000000
    interval_minutes: 5

portfolio:
  enabled: true
  total_capital_pct: 0.8    # 总仓位上限（占总资金比例）
  max_strategy_weight: 0.5
  min_strategy_weight: 0.05
  lookback_days: 90         # 计算策略绩效的回看天数
  rebalance_interval: "weekly"
  rebalance_drift_threshold: 0.2
  risk:
    strategy_daily_loss_limit: 0.03
    portfolio_drawdown_limit: 0.05
```

## 8. 依赖新增

```
# sentiment
snscrape              # Twitter 抓取
telethon              # Telegram 监听
vaderSentiment        # 基础 NLP 情绪分析
feedparser            # RSS 解析

# portfolio
riskfolio-lib         # 组合优化（CVaR）
quantstats            # 绩效报告
```

## 9. 数据存储扩展

在现有 `scanner.db` 中新增表：

```sql
-- 舆情原始数据
CREATE TABLE sentiment_items (
    id INTEGER PRIMARY KEY,
    source TEXT,
    symbol TEXT,
    score REAL,
    confidence REAL,
    raw_text TEXT,
    timestamp TEXT
);

-- 聚合情绪信号
CREATE TABLE sentiment_signals (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    score REAL,
    direction TEXT,
    confidence REAL,
    created_at TEXT
);

-- 组合每日净值
CREATE TABLE portfolio_nav (
    date TEXT PRIMARY KEY,
    nav REAL,
    high_water_mark REAL
);

-- 策略权重历史
CREATE TABLE strategy_weights (
    id INTEGER PRIMARY KEY,
    date TEXT,
    strategy_id TEXT,
    weight REAL,
    sharpe REAL,
    win_rate REAL,
    max_drawdown REAL
);

-- 风控事件
CREATE TABLE risk_events (
    id INTEGER PRIMARY KEY,
    level TEXT,           -- "position" / "strategy" / "portfolio"
    strategy_id TEXT,
    event_type TEXT,      -- "stop_loss" / "daily_limit" / "drawdown_halt"
    details TEXT,
    created_at TEXT
);
```

## 10. 降级与容错

| 场景 | 降级策略 |
|------|---------|
| 舆情模块整体不可用 | sentiment_boost = 0，纯技术面运行 |
| 单个数据源失败 | 跳过该源，用剩余源加权（自动归一化权重） |
| 组合优化求解失败 | 回退到等权分配 |
| 绩效数据不足 90 天 | 用可用数据计算，不足 30 天的策略用等权 |
| Telegram 账号被限流 | 自动降频至 1 req/min，记录 risk_event |
