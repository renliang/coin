# 扫描历史 UI 改版设计文档

**日期：** 2026-04-13  
**状态：** 已批准  
**范围：** `history_ui/` 模块重构

---

## 背景与目标

现有 `history_ui` 页面存在以下问题：

- 只展示扫描结果，没有持仓/交易历史
- 查某个币种的全部历史需要手动翻页，体验差
- 筛选条件全部是纯文本输入，时间格式需要手动填写
- 扫描记录与持仓记录无法对照查看，无法复盘"信号→开仓→结果"链路

目标：在保持 Flask + Jinja2 技术栈不变的前提下，重新设计页面结构，让用户能快速搜索某个币种并看到完整的扫描+持仓历史。

---

## 技术选型

- **后端：** Flask + Jinja2（服务端渲染，不引入前端构建工具）
- **前端：** 原生 HTML + CSS，无 JS 框架依赖
- **数据库：** 现有 `scanner.db`（SQLite），复用 `scanner/tracker.py` 现有函数

---

## 整体架构

```
history_ui/
├── app.py               # 新增 /coin/<symbol> 路由，/ 路由改为汇总视图
├── templates/
│   ├── base.html        # 新增：公共 layout（顶部导航 + 搜索框）
│   ├── index.html       # 改版：币种汇总列表（替换原 history.html）
│   └── coin.html        # 新增：币种详情页（扫描 + 持仓双区块）
└── static/
    └── style.css        # 增强样式（高亮规则、表格优化）
```

### 路由设计

| 路由 | 功能 | 数据来源 |
|------|------|---------|
| `GET /` | 币种汇总列表 | `get_tracked_symbols()` |
| `GET /coin/<symbol>` | 币种详情（扫描 + 持仓） | `query_scan_results()` + `get_closed_trades()` |

### URL 规范

- symbol 中的 `/` 替换为 `-`，避免 URL 歧义（如 `BTC/USDT` → `/coin/BTC-USDT`）
- 路由层做反向转换（`-` → `/`）后再查询数据库

---

## 页面设计

### 公共导航（base.html）

所有页面顶部共用：
- 左侧：标题"扫描历史"，点击回首页
- 右侧：搜索框 + Go 按钮，输入币种名（如 `BTC/USDT` 或 `BTC-USDT`）提交跳转 `/coin/<symbol>`

### 首页 `/`（index.html）

默认展示所有被追踪过的币种汇总，按出现次数降序排列。

**列：**

| 列 | 说明 |
|----|------|
| 币种 | symbol，整行可点击，跳转到详情页 |
| 出现次数 | 被扫描到的总次数 |
| 最新分数 | 最近一次扫描得分 |
| 最后扫描时间 | 最近被扫描到的时间 |

- 不分页，全量展示（币种总数量有限）
- 无复杂筛选条件，只有搜索框用于精确跳转

### 详情页 `/coin/<symbol>`（coin.html）

页面分两个区块，按时间倒序分别展示该币种的扫描记录和持仓历史。

#### 区块一：扫描记录

- 全量展示（最多取 500 条），不分页
- 按扫描时间倒序排列

**列：** 扫描时间 / 分数 / 跌幅% / 量比 / 窗口天数 / 模式

**高亮规则：**
- 分数 ≥ 0.75：绿色背景
- 分数 ≤ 0.60：黄色背景

#### 区块二：持仓历史

- 只展示 `status='closed'` 的持仓记录
- 按平仓时间倒序排列
- 若无记录，显示"暂无持仓历史"

**列：** 开仓时间 / 方向 / 入场价 / 平仓价 / 盈亏% / 平仓原因

**高亮规则：**
- 盈亏% > 0：绿色
- 盈亏% < 0：红色

---

## 后端改动范围

### `scanner/tracker.py`

无需修改，复用现有函数：
- `get_tracked_symbols()` — 首页汇总数据
- `query_scan_results(symbol, per_page=500)` — 详情页扫描记录
- `get_closed_trades()` — 详情页持仓历史（在路由层按 symbol 过滤）

### `history_ui/app.py`

新增路由 `/coin/<symbol>`，改造 `/` 路由，逻辑如下：

```python
@app.route("/")
def index():
    # 调用 get_tracked_symbols() 渲染汇总列表

@app.route("/coin/<path:symbol_slug>")
def coin_detail(symbol_slug):
    symbol = symbol_slug.replace("-", "/")  # BTC-USDT → BTC/USDT
    scans, _ = query_scan_results(symbol=symbol, per_page=500)
    all_trades = get_closed_trades()
    trades = [t for t in all_trades if t["symbol"] == symbol]
    # 渲染 coin.html
```

---

## 错误处理

- `/coin/<symbol>` 访问不存在的币种：正常渲染，两个区块均显示"暂无记录"
- 数据库文件不存在：Flask 会捕获 sqlite3 异常，返回 500（现有行为，不改）

---

## 不在范围内

- 实时数据刷新（无 JS，需手动刷新）
- 订单历史（`orders` 表）展示
- 开仓中持仓的展示（只展示已平仓）
- 扫描记录与持仓记录的时间轴关联视图
