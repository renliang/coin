# History UI 改进设计

**日期：** 2026-04-13  
**状态：** 已审批

## 问题背景

现有 history_ui 存在三个问题：
1. 扫描记录里没有入场/止损/止盈点位 —— `save_scan()` 在 `generate_signals()` 之前调用，信号点位数据从未写入数据库
2. divergence/breakout 模式的量比、跌幅全是 0 —— 这两种模式本来就没这两个指标，被硬编码成 0 存进去
3. 首页无法按模式筛选历史 —— `history.html` 模板有筛选表单但无对应路由，是孤立模板

## 目标

1. 扫描记录能显示入场/止损/止盈价
2. 首页展示今日各模式扫描结果（tab 切换）
3. 独立历史页支持按 symbol、模式、时间筛选

---

## 数据层

### scan_results 表新增列

使用 `ALTER TABLE` 迁移，存量数据这几列为 NULL：

```sql
ALTER TABLE scan_results ADD COLUMN entry_price      REAL;
ALTER TABLE scan_results ADD COLUMN stop_loss_price  REAL;
ALTER TABLE scan_results ADD COLUMN take_profit_price REAL;
ALTER TABLE scan_results ADD COLUMN signal_type      TEXT DEFAULT '';
```

### save_scan() 签名变更

```python
# 改前
def save_scan(results: list[dict], mode: str = "accumulation") -> int

# 改后
def save_scan(signals: list[TradeSignal], mode: str = "accumulation") -> int
```

写入时包含 `entry_price / stop_loss_price / take_profit_price / signal_type`。  
`drop_pct / volume_ratio` 从 `TradeSignal` 读取（divergence/breakout 模式这两个字段本来就是 0，UI 展示时判断为 0 则显示 `—`）。

### main.py 执行顺序调整

三个模式（accumulation / divergence / breakout）统一改为：

```
ranked → generate_signals(ranked, signal_config) → save_scan(signals, mode) → 输出
```

注意：`generate_signals()` 按 `min_score` 过滤，低于阈值的不存；`save_scan` 存的是信号列表而非全量 ranked。

### query_scan_results() 更新

SELECT 补充 `entry_price / stop_loss_price / take_profit_price / signal_type` 四列，返回的 dict 包含这些字段（可为 None）。

新增辅助函数 `get_today_scans(mode: str) -> list[dict]`，查询今天该模式最新一次扫描（取最大 scan_id）的信号列表。

---

## 路由层

| 路由 | 说明 |
|------|------|
| `GET /` | 首页，今日扫描（三 tab） |
| `GET /history` | 历史页，全量列表带筛选 |
| `GET /coin/<symbol>` | 币种详情（不变） |
| `GET /search?symbol=` | 跳转币种详情（不变） |

### `GET /` 参数

无查询参数，后端为每个 tab 查一次 `get_today_scans(mode)`，传入模板：

```python
return render_template("index.html",
    accum=get_today_scans("accumulation"),
    div=get_today_scans("divergence"),
    breakout=get_today_scans("breakout"),
)
```

### `GET /history` 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | str | 可选，精确匹配 |
| `mode` | str | 可选，accumulation / divergence / breakout |
| `scan_time_from` | str | 可选，格式 `YYYY-MM-DD HH:MM:SS` |
| `scan_time_to` | str | 同上 |
| `page` | int | 默认 1 |
| `per_page` | int | 默认 50，上限 200 |

---

## 模板层

### index.html（改造）

```
┌─────────────────────────────────────┐
│  今日扫描  [历史记录 →]               │  ← 顶部导航，右侧跳 /history
├─────────────────────────────────────┤
│  [accumulation] [divergence] [breakout] │  ← tab 切换（JS 纯前端）
├─────────────────────────────────────┤
│  币种 | 得分 | 入场价 | 止损价 | 止盈价 │
│  ...                                │
└─────────────────────────────────────┘
```

Tab 切换用 HTML/CSS（无需后端请求），三组数据同时渲染到 DOM，JS 控制显示/隐藏。

### history.html（复用现有模板，修复路由+改造）

```
┌─────────────────────────────────────┐
│  ← 今日扫描   全量历史               │
├─────────────────────────────────────┤
│  [币种] [模式▼] [时间起] [时间止] [筛选] │
├─────────────────────────────────────┤
│  扫描时间 | 币种 | 模式 | 得分 | 入场价 | 止损价 | 止盈价 │
│  ...                                │
├─────────────────────────────────────┤
│  [上一页]  第 N / M 页  [下一页]     │
└─────────────────────────────────────┘
```

模式筛选用 `<select>` 下拉（全部 / accumulation / divergence / breakout）。

---

## 文件变更地图

| 操作 | 文件 | 改动 |
|------|------|------|
| Modify | `scanner/tracker.py` | `ALTER TABLE` 迁移；`save_scan()` 接受 `list[TradeSignal]`；`query_scan_results()` 补列；新增 `get_today_scans()` |
| Modify | `main.py` | 三个模式改为先 `generate_signals()` 再 `save_scan(signals)` |
| Modify | `history_ui/app.py` | `index()` 改为查今日扫描；新增 `history()` 路由 |
| Modify | `history_ui/templates/index.html` | 今日扫描 + tab 切换 |
| Modify | `history_ui/templates/history.html` | 全量历史列表 + 筛选表单（修复孤立模板） |
| Modify | `tests/test_tracker.py` | 更新 `save_scan` 相关测试 |

---

## 测试覆盖

- `save_scan(signals)` 正确写入 4 个新列
- `query_scan_results()` 返回新列字段
- `get_today_scans(mode)` 返回最新一次扫描，跨天不返回旧数据
- accumulation 模式 `drop_pct / volume_ratio` 有值时正确存取
- divergence 模式 `entry/sl/tp` 正确存取，`drop_pct = 0` 时 UI 显示 `—`
