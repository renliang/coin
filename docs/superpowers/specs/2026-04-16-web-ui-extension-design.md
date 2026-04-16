# Web UI 扩展：Dashboard + 舆情 + 组合页面 + Playwright 测试

> 日期：2026-04-16
> 状态：设计阶段

## 1. 目标

在现有 React SPA（`web/`）中新增 3 个页面（Dashboard、舆情、组合），并用 Playwright 做冒烟 + 功能测试。

## 2. 新增后端 API

在 `history_ui/api.py` 中新增端点：

```
GET  /api/sentiment/latest          — 各币种最新情绪信号
GET  /api/sentiment/history         — 情绪分值时序数据（?symbol=&days=7）
GET  /api/sentiment/items           — 原始舆情条目（?source=&symbol=&page=1&per_page=20）
GET  /api/portfolio/status          — 当前权重 + NAV + 风控状态
GET  /api/portfolio/nav-history     — NAV 历史曲线（?days=90）
GET  /api/portfolio/weights-history — 权重变化历史（?days=90）
GET  /api/portfolio/risk-events     — 风控事件列表（?limit=20）
POST /api/portfolio/rebalance       — 触发再平衡
```

## 3. 新增前端页面

### 3.1 Dashboard（/app/dashboard）

综合首页，汇总关键指标：

- **总净值卡片** — 当前 NAV + 日涨跌幅
- **市场情绪指示器** — 全局情绪分值（恐惧/中性/贪婪色彩标识）
- **策略权重饼图** — Recharts PieChart
- **最近风控事件** — 最近 5 条，带 level 颜色标识
- **最近扫描信号** — 最近 10 条，复用现有 signal 数据

### 3.2 舆情页面（/app/sentiment）

- **情绪总览表格** — 各币种 score/direction/confidence/更新时间
- **数据源分布柱状图** — Recharts BarChart，按 source 统计条数
- **情绪趋势折线图** — Recharts LineChart，最近 7 天历史
- **原始条目列表** — 可按 source/symbol 筛选，分页展示

### 3.3 组合页面（/app/portfolio）

- **策略权重** — 饼图 + 详情表格（权重、夏普、胜率、最大回撤）
- **NAV 曲线** — Recharts LineChart + 高水位线标注
- **风控状态** — 组合是否暂停、被暂停的策略列表
- **风控事件时间线** — 最近 20 条
- **再平衡按钮** — POST 触发，显示新权重结果

## 4. 文件结构

### 后端

```
history_ui/
└── api.py                    # 修改：新增 sentiment/portfolio API 端点
```

### 前端

```
web/src/
├── pages/
│   ├── DashboardPage.tsx     # 新增
│   ├── SentimentPage.tsx     # 新增
│   └── PortfolioPage.tsx     # 新增
├── components/
│   ├── SentimentTable.tsx    # 新增：情绪信号表格
│   ├── SentimentChart.tsx    # 新增：情绪趋势图
│   ├── SourceDistribution.tsx# 新增：数据源分布图
│   ├── SentimentItems.tsx    # 新增：原始条目列表
│   ├── WeightsPieChart.tsx   # 新增：策略权重饼图
│   ├── NavChart.tsx          # 新增：NAV 曲线
│   ├── RiskStatus.tsx        # 新增：风控状态
│   ├── RiskEvents.tsx        # 新增：风控事件列表
│   └── StatCard.tsx          # 新增：数值卡片
├── api/
│   ├── sentiment.ts          # 新增：舆情 API 调用
│   └── portfolio.ts          # 新增：组合 API 调用
└── App.tsx                   # 修改：新增路由
```

### Playwright 测试

```
tests/e2e/
├── conftest.py               # fixtures：启动 Flask server + seed 数据 + cleanup
├── test_dashboard.py         # Dashboard 冒烟 + 功能
├── test_sentiment.py         # 舆情 冒烟 + 功能
└── test_portfolio.py         # 组合 冒烟 + 功能
```

## 5. API 响应格式

### GET /api/sentiment/latest

```json
{
  "signals": [
    {"symbol": "BTC/USDT", "score": 0.65, "direction": "bullish", "confidence": 0.85, "created_at": "2026-04-16 12:00:00"},
    {"symbol": "ETH/USDT", "score": -0.3, "direction": "bearish", "confidence": 0.7, "created_at": "2026-04-16 12:00:00"}
  ]
}
```

### GET /api/sentiment/history?symbol=BTC/USDT&days=7

```json
{
  "history": [
    {"date": "2026-04-10", "score": 0.4, "direction": "bullish"},
    {"date": "2026-04-11", "score": 0.55, "direction": "bullish"}
  ]
}
```

### GET /api/sentiment/items?source=twitter&symbol=BTC/USDT&page=1&per_page=20

```json
{
  "items": [
    {"id": 1, "source": "twitter", "symbol": "BTC/USDT", "score": 0.8, "confidence": 0.9, "raw_text": "BTC moon!", "timestamp": "2026-04-16 12:00:00"}
  ],
  "total": 150,
  "page": 1,
  "per_page": 20
}
```

### GET /api/portfolio/status

```json
{
  "weights": {"divergence": 0.4, "accumulation": 0.35, "breakout": 0.25},
  "nav": 10500.0,
  "high_water_mark": 10500.0,
  "drawdown_pct": 0.0,
  "portfolio_halted": false,
  "halted_strategies": []
}
```

### GET /api/portfolio/nav-history?days=90

```json
{
  "history": [
    {"date": "2026-04-15", "nav": 10000.0, "high_water_mark": 10000.0},
    {"date": "2026-04-16", "nav": 10500.0, "high_water_mark": 10500.0}
  ]
}
```

### GET /api/portfolio/weights-history?days=90

```json
{
  "history": [
    {"date": "2026-04-16", "weights": {"divergence": 0.4, "accumulation": 0.35, "breakout": 0.25}}
  ]
}
```

### GET /api/portfolio/risk-events?limit=20

```json
{
  "events": [
    {"id": 1, "level": "strategy", "strategy_id": "divergence", "event_type": "daily_limit", "details": "loss exceeded 3%", "created_at": "2026-04-16 10:00:00"}
  ]
}
```

### POST /api/portfolio/rebalance

```json
{
  "success": true,
  "weights": {"divergence": 0.45, "accumulation": 0.30, "breakout": 0.25}
}
```

## 6. Playwright 测试

### conftest.py

- `seed_db` fixture：向 SQLite 插入测试数据（sentiment_items, sentiment_signals, portfolio_nav, strategy_weights, risk_events）
- `flask_server` fixture：启动 Flask 在随机端口，yield URL，测试后关闭
- `page` fixture：Playwright page 实例

### 冒烟测试（每个页面）

- 页面加载状态码 200
- 页面标题/heading 元素存在
- 无 console.error
- 表格/图表容器元素存在

### 功能测试

**Dashboard:**
- NAV 卡片显示数值（非"--"）
- 情绪指示器显示方向文字
- 策略权重饼图 SVG 渲染

**Sentiment:**
- 情绪表格行数 > 0
- 选择 source 筛选后表格更新
- 趋势图有数据点（SVG path 或 circle 元素）
- 原始条目分页翻页后 URL 参数变化

**Portfolio:**
- NAV 曲线 SVG 渲染
- 权重表格显示策略名称和百分比
- 点击再平衡按钮后显示成功提示
- 风控事件列表条目存在

## 7. 技术约束

- 复用现有 React 技术栈：React 19 + TypeScript + Vite + Recharts + Tailwind CSS
- 复用现有 Flask API 层（history_ui/api.py）
- Playwright 测试用 Python（pytest-playwright），与现有 pytest 测试共存
- 测试数据通过 fixture 直接写 SQLite，不依赖外部 API
