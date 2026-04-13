# History UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 `history_ui` 模块，新增币种汇总首页和带扫描+持仓双区块的币种详情页，替代现有单表格+分页设计。

**Architecture:** 双路由设计：`/` 展示所有被追踪币种汇总列表，`/coin/<symbol>` 展示该币种的完整扫描记录和已平仓持仓历史。新增公共 `base.html` layout，搜索框提交到 `/search` 后重定向至详情页。后端复用 `scanner/tracker.py` 现有函数，仅对 `get_tracked_symbols()` 补充 `last_score` 字段。

**Tech Stack:** Python 3.13 / Flask / Jinja2 / SQLite / pytest

---

## 文件地图

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `scanner/tracker.py` | `get_tracked_symbols()` 补充 `last_score` 子查询 |
| Modify | `history_ui/app.py` | 重写 `/` 路由，新增 `/coin/<path:symbol_slug>` 和 `/search` 路由 |
| Create | `history_ui/templates/base.html` | 公共 layout：顶部导航 + 搜索框 |
| Create | `history_ui/templates/index.html` | 币种汇总列表页 |
| Create | `history_ui/templates/coin.html` | 币种详情页（扫描 + 持仓） |
| Modify | `history_ui/static/style.css` | 补充导航、可点击行、得分/盈亏高亮样式 |
| Modify | `tests/test_history_ui.py` | 更新旧测试 + 新增路由测试 |

---

## Task 1: 为 `get_tracked_symbols()` 补充 `last_score` 字段

**Files:**
- Modify: `scanner/tracker.py:306-321`

- [ ] **Step 1: 在 `get_tracked_symbols()` 的 SQL 中加入 `last_score` 子查询**

将 `scanner/tracker.py` 中 `get_tracked_symbols()` 函数替换为：

```python
def get_tracked_symbols() -> list[dict]:
    """获取所有被跟踪的币种及其出现次数、最新价格和最新得分"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT r.symbol, COUNT(*) as times,
               MAX(s.scan_time) as last_seen,
               (SELECT r2.price FROM scan_results r2 JOIN scans s2 ON r2.scan_id = s2.id
                WHERE r2.symbol = r.symbol ORDER BY s2.scan_time DESC LIMIT 1) as last_price,
               (SELECT r2.price FROM scan_results r2 JOIN scans s2 ON r2.scan_id = s2.id
                WHERE r2.symbol = r.symbol ORDER BY s2.scan_time ASC LIMIT 1) as first_price,
               (SELECT r2.score FROM scan_results r2 JOIN scans s2 ON r2.scan_id = s2.id
                WHERE r2.symbol = r.symbol ORDER BY s2.scan_time DESC LIMIT 1) as last_score
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        GROUP BY r.symbol
        ORDER BY times DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: 验证现有测试仍然通过**

```bash
cd /Users/edy/Desktop/workspace/coin
.venv/bin/pytest tests/test_history_ui.py tests/test_trader_db.py -v
```

预期：所有测试通过（`get_tracked_symbols` 无现有测试，其他不受影响）

- [ ] **Step 3: Commit**

```bash
git add scanner/tracker.py
git commit -m "feat: add last_score field to get_tracked_symbols"
```

---

## Task 2: 更新旧测试以匹配新 `/` 路由行为

**Files:**
- Modify: `tests/test_history_ui.py`

- [ ] **Step 1: 更新 `temp_db` fixture，加入 positions 表**

在 `tests/test_history_ui.py` 的 `temp_db` fixture 中，`executescript` 追加 positions 表（`_get_conn()` 会自动创建，但为了确保测试环境一致，显式创建更可靠）。将 `executescript` 内容替换为：

```python
    conn.executescript(
        """
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL
        );
        CREATE TABLE scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            market_cap_m REAL,
            drop_pct REAL NOT NULL,
            volume_ratio REAL NOT NULL,
            window_days INTEGER NOT NULL,
            score REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'accumulation',
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            size REAL NOT NULL,
            leverage INTEGER NOT NULL,
            score REAL NOT NULL,
            tp_order_id TEXT,
            sl_order_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            exit_reason TEXT,
            mode TEXT DEFAULT ''
        );
        """
    )
```

- [ ] **Step 2: 更新 `test_history_page2`（旧行为：分页；新行为：汇总列表无分页）**

将 `test_history_page2` 函数替换为：

```python
def test_history_index_shows_all_symbols(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    # 首页显示所有追踪币种
    assert "BTC/USDT".encode("utf-8") in r.data
    assert "ETH/USDT".encode("utf-8") in r.data
    # 显示出现次数
    assert "2".encode("utf-8") in r.data  # BTC/USDT 出现 2 次
```

- [ ] **Step 3: 运行测试，确认 `test_history_index_shows_all_symbols` 失败（路由还未改）**

```bash
.venv/bin/pytest tests/test_history_ui.py::test_history_index_shows_all_symbols -v
```

预期：FAIL，因为 `/` 路由还未返回汇总列表

- [ ] **Step 4: Commit（仅测试文件）**

```bash
git add tests/test_history_ui.py
git commit -m "test: update history UI tests for new index page behavior"
```

---

## Task 3: 创建 `base.html` 和 `index.html` 模板

**Files:**
- Create: `history_ui/templates/base.html`
- Create: `history_ui/templates/index.html`

- [ ] **Step 1: 创建 `history_ui/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}扫描历史{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <header class="site-header">
    <a class="site-title" href="{{ url_for('index') }}">扫描历史</a>
    <form class="site-search" action="{{ url_for('search') }}" method="get">
      <input type="text" name="symbol" placeholder="BTC/USDT" autocomplete="off">
      <button type="submit">Go</button>
    </form>
  </header>
  <main class="site-main">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 2: 创建 `history_ui/templates/index.html`**

```html
{% extends "base.html" %}
{% block title %}扫描历史{% endblock %}
{% block content %}
<p class="summary">共追踪 <strong>{{ symbols|length }}</strong> 个币种</p>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>币种</th>
        <th>出现次数</th>
        <th>最新分数</th>
        <th>最后扫描时间</th>
      </tr>
    </thead>
    <tbody>
      {% for row in symbols %}
      <tr>
        <td><a class="symbol-link" href="{{ url_for('coin_detail', symbol_slug=row.symbol) }}">{{ row.symbol }}</a></td>
        <td>{{ row.times }}</td>
        <td>{{ '%.4f'|format(row.last_score) if row.last_score is not none else '—' }}</td>
        <td>{{ row.last_seen }}</td>
      </tr>
      {% else %}
      <tr><td colspan="4" class="muted center">无数据</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 3: 确认文件已创建**

```bash
ls history_ui/templates/
```

预期输出包含：`base.html  coin.html（还未创建）  history.html  index.html`

---

## Task 4: 重写 `app.py` 的 `/` 路由

**Files:**
- Modify: `history_ui/app.py`

- [ ] **Step 1: 将 `app.py` 全量替换为以下内容（保留原 main() 不变）**

```python
import os

from flask import Flask, redirect, render_template, request, url_for

from scanner.tracker import get_closed_trades, get_tracked_symbols, query_scan_results


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.route("/")
    def index():
        symbols = get_tracked_symbols()
        return render_template("index.html", symbols=symbols)

    @app.route("/search")
    def search():
        symbol = request.args.get("symbol", "").strip().upper().replace("-", "/")
        if not symbol:
            return redirect(url_for("index"))
        return redirect(url_for("coin_detail", symbol_slug=symbol))

    @app.route("/coin/<path:symbol_slug>")
    def coin_detail(symbol_slug: str):
        symbol = symbol_slug.upper()
        scans, _ = query_scan_results(symbol=symbol, per_page=500)
        all_trades = get_closed_trades()
        trades = [t for t in all_trades if t["symbol"] == symbol]
        return render_template(
            "coin.html",
            symbol=symbol,
            scans=scans,
            trades=trades,
        )

    return app


def main() -> None:
    host = os.environ.get("HISTORY_UI_HOST", "127.0.0.1")
    port_s = os.environ.get("HISTORY_UI_PORT", "5050")
    try:
        port = int(port_s)
    except ValueError:
        port = 5050
    debug = os.environ.get("HISTORY_UI_DEBUG", "").lower() in ("1", "true", "yes")
    app = create_app()
    app.run(host=host, port=port, debug=debug)
```

- [ ] **Step 2: 运行测试，`test_history_index_shows_all_symbols` 应通过，但 `coin_detail` 模板还未创建会导致其他测试可能出错**

```bash
.venv/bin/pytest tests/test_history_ui.py::test_history_index_shows_all_symbols \
                 tests/test_history_ui.py::test_history_index_200 -v
```

预期：两个测试均 PASS

- [ ] **Step 3: Commit**

```bash
git add history_ui/app.py history_ui/templates/base.html history_ui/templates/index.html
git commit -m "feat: rewrite history UI index page with coin summary list"
```

---

## Task 5: 新增 `/coin/<symbol>` 路由测试

**Files:**
- Modify: `tests/test_history_ui.py`

- [ ] **Step 1: 在 `temp_db` fixture 中插入一条已平仓持仓记录**

在 `temp_db` fixture 的 `conn.commit()` 之前插入：

```python
    conn.execute(
        "INSERT INTO positions (symbol, side, entry_price, size, leverage, score, "
        "status, opened_at, closed_at, exit_price, pnl, pnl_pct, exit_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTC/USDT", "long", 95000.0, 0.01, 10, 0.82,
         "closed", "2026-01-10 09:00:00", "2026-01-11 09:00:00",
         98000.0, 30.0, 3.16, "TP"),
    )
```

- [ ] **Step 2: 追加三个新测试函数**

```python
def test_coin_detail_200(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/coin/BTC/USDT")
    assert r.status_code == 200
    assert "BTC/USDT".encode("utf-8") in r.data
    # 扫描记录区块
    assert "扫描记录".encode("utf-8") in r.data
    # 持仓历史区块
    assert "持仓历史".encode("utf-8") in r.data


def test_coin_detail_shows_scan_and_trade(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/coin/BTC/USDT")
    assert r.status_code == 200
    # 有 2 条扫描记录
    assert r.data.count(b"accumulation") >= 2
    # 有 1 条持仓记录（TP）
    assert "TP".encode("utf-8") in r.data
    assert "+3.16".encode("utf-8") in r.data or "3.16".encode("utf-8") in r.data


def test_search_redirects_to_coin_detail(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/search?symbol=BTC%2FUSDT")
    assert r.status_code == 302
    assert "/coin/BTC/USDT" in r.headers["Location"]
```

- [ ] **Step 3: 运行新测试，确认 FAIL（coin.html 还未创建）**

```bash
.venv/bin/pytest tests/test_history_ui.py::test_coin_detail_200 \
                 tests/test_history_ui.py::test_search_redirects_to_coin_detail -v
```

预期：`test_coin_detail_200` FAIL（TemplateNotFound），`test_search_redirects_to_coin_detail` PASS（路由已有）

- [ ] **Step 4: Commit**

```bash
git add tests/test_history_ui.py
git commit -m "test: add coin detail and search redirect tests"
```

---

## Task 6: 创建 `coin.html` 详情页模板

**Files:**
- Create: `history_ui/templates/coin.html`

- [ ] **Step 1: 创建 `history_ui/templates/coin.html`**

```html
{% extends "base.html" %}
{% block title %}{{ symbol }} — 扫描历史{% endblock %}
{% block content %}
<div class="page-back">
  <a href="{{ url_for('index') }}">← 返回列表</a>
  <h2 class="page-symbol">{{ symbol }}</h2>
</div>

<section class="card">
  <h3 class="card-title">扫描记录（{{ scans|length }} 条）</h3>
  {% if scans %}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>扫描时间</th>
          <th>分数</th>
          <th>跌幅%</th>
          <th>量比</th>
          <th>窗口天</th>
          <th>模式</th>
        </tr>
      </thead>
      <tbody>
        {% for row in scans %}
        <tr class="
          {%- if row.score >= 0.75 %} score-high
          {%- elif row.score <= 0.60 %} score-low
          {%- endif %}">
          <td>{{ row.scan_time }}</td>
          <td>{{ '%.4f'|format(row.score) }}</td>
          <td>{{ '%.2f'|format(row.drop_pct) }}</td>
          <td>{{ '%.4f'|format(row.volume_ratio) }}</td>
          <td>{{ row.window_days }}</td>
          <td>{{ row.mode }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="muted">暂无扫描记录</p>
  {% endif %}
</section>

<section class="card">
  <h3 class="card-title">持仓历史（{{ trades|length }} 条）</h3>
  {% if trades %}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>开仓时间</th>
          <th>方向</th>
          <th>入场价</th>
          <th>平仓价</th>
          <th>盈亏%</th>
          <th>平仓原因</th>
        </tr>
      </thead>
      <tbody>
        {% for t in trades %}
        <tr class="
          {%- if t.pnl_pct is not none and t.pnl_pct > 0 %} pnl-pos
          {%- elif t.pnl_pct is not none and t.pnl_pct < 0 %} pnl-neg
          {%- endif %}">
          <td>{{ t.opened_at }}</td>
          <td>{{ t.side }}</td>
          <td>{{ '%.6f'|format(t.entry_price) }}</td>
          <td>{{ '%.6f'|format(t.exit_price) if t.exit_price is not none else '—' }}</td>
          <td>
            {%- if t.pnl_pct is not none -%}
              {%- if t.pnl_pct > 0 %}+{% endif %}{{ '%.2f'|format(t.pnl_pct) }}%
            {%- else -%}—{%- endif -%}
          </td>
          <td>{{ t.exit_reason if t.exit_reason else '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="muted">暂无持仓历史</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: 运行测试，所有新测试应通过**

```bash
.venv/bin/pytest tests/test_history_ui.py -v
```

预期：所有测试 PASS

- [ ] **Step 3: Commit**

```bash
git add history_ui/templates/coin.html
git commit -m "feat: add coin detail page with scan and position history"
```

---

## Task 7: 增强 `style.css`

**Files:**
- Modify: `history_ui/static/style.css`

- [ ] **Step 1: 在 `style.css` 末尾追加以下样式**

```css
/* 顶部导航 */
.site-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 0 1rem;
  border-bottom: 1px solid #e5e5e5;
  margin-bottom: 1.25rem;
}

.site-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: #1a1a1a;
  text-decoration: none;
}

.site-title:hover {
  color: #2563eb;
}

.site-search {
  display: flex;
  gap: 0.4rem;
}

.site-search input[type="text"] {
  padding: 0.35rem 0.6rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  min-width: 12rem;
}

.site-search button {
  padding: 0.35rem 0.8rem;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
}

.site-search button:hover {
  background: #1d4ed8;
}

.site-main {
  padding-top: 0.5rem;
}

/* 币种链接 */
.symbol-link {
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.symbol-link:hover {
  text-decoration: underline;
}

/* 详情页顶部 */
.page-back {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.page-back a {
  color: #2563eb;
  text-decoration: none;
  font-size: 0.9rem;
}

.page-back a:hover {
  text-decoration: underline;
}

.page-symbol {
  margin: 0;
  font-size: 1.35rem;
}

/* 卡片区块 */
.card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}

.card-title {
  margin: 0 0 0.75rem;
  font-size: 1rem;
  font-weight: 600;
}

/* 得分高亮 */
.score-high {
  background: #f0fdf4;
}

.score-high:hover {
  background: #dcfce7;
}

.score-low {
  background: #fefce8;
}

.score-low:hover {
  background: #fef9c3;
}

/* 盈亏颜色 */
.pnl-pos td:nth-child(5) {
  color: #16a34a;
  font-weight: 600;
}

.pnl-neg td:nth-child(5) {
  color: #dc2626;
  font-weight: 600;
}
```

- [ ] **Step 2: 运行全量测试确认无回归**

```bash
.venv/bin/pytest tests/test_history_ui.py -v
```

预期：所有测试 PASS

- [ ] **Step 3: Commit**

```bash
git add history_ui/static/style.css
git commit -m "style: add navigation, card sections, and score/pnl highlight styles"
```

---

## Task 8: 全量测试 + 最终 Commit

**Files:** 无新文件

- [ ] **Step 1: 运行全部测试**

```bash
.venv/bin/pytest tests/ -v
```

预期：所有测试通过，无失败

- [ ] **Step 2: 手动启动确认页面可访问**

```bash
.venv/bin/python -m history_ui
# 访问 http://127.0.0.1:5050
# 访问 http://127.0.0.1:5050/coin/BTC/USDT
```

预期：首页展示币种列表，详情页展示扫描+持仓双区块

- [ ] **Step 3: 如无问题，tag 本次改版完成**

```bash
git log --oneline -6
```

预期：看到 Task 1-7 的 6 条 commit
