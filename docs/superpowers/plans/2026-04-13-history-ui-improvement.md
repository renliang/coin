# History UI 改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 history_ui 中展示入场/止损/止盈点位，首页改为今日扫描三 tab，新增 /history 全量历史筛选页。

**Architecture:** 在 `TradeSignal` 加 `market_cap_m` 字段，`save_scan()` 改为接受 `list[TradeSignal]`，`main.py` 三个模式改为先 `generate_signals()` 再 `save_scan(signals)`。`_get_conn()` 迁移 `scan_results` 表新增 4 列。`history_ui/app.py` 新增 `history()` 路由，`index()` 改为查今日扫描。

**Tech Stack:** Python 3.13 / SQLite / Flask / Jinja2 / pytest

---

## 文件地图

| 操作 | 文件 | 改动内容 |
|------|------|---------|
| Modify | `scanner/signal.py` | `TradeSignal` 加 `market_cap_m: float = 0`；`generate_signals()` 从 match dict 读取 market_cap_m |
| Modify | `scanner/tracker.py` | `_get_conn()` 加 4 列迁移；`save_scan()` 改接受 `list[TradeSignal]`；`query_scan_results()` SELECT 补 4 列；新增 `get_today_scans()` |
| Modify | `main.py` | 三个模式改为先 `generate_signals()` 再 `save_scan(signals, mode)` |
| Modify | `history_ui/app.py` | `index()` 改查今日扫描；新增 `history()` 路由；更新 import |
| Modify | `history_ui/templates/index.html` | 今日扫描 + 三 tab + 链接到 /history |
| Modify | `history_ui/templates/history.html` | 全量历史列表 + 筛选表单（修复孤立模板） |
| Create | `tests/test_tracker.py` | save_scan / query_scan_results / get_today_scans 测试 |

---

## Task 1：TradeSignal 加 market_cap_m，generate_signals 传递它

**Files:**
- Modify: `scanner/signal.py:36-50`（TradeSignal dataclass）、`scanner/signal.py:64-113`（generate_signals）
- Test: `tests/test_signal.py`

`TradeSignal` 目前没有 `market_cap_m`，但 `scan_results` 表存储了它。要让 `save_scan(signals)` 能写入此字段，需要 TradeSignal 携带它。

- [ ] **Step 1: 在 `tests/test_signal.py` 末尾追加失败测试**

```python
def test_market_cap_m_copied_from_match():
    """generate_signals 应将 match 里的 market_cap_m 复制到 TradeSignal。"""
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 2.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14,
         "market_cap_m": 999.5},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0)
    signals = generate_signals(matches, config)
    assert len(signals) == 1
    assert signals[0].market_cap_m == 999.5


def test_market_cap_m_defaults_to_zero():
    """match 没有 market_cap_m 时，TradeSignal.market_cap_m 默认为 0。"""
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 2.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0)
    signals = generate_signals(matches, config)
    assert signals[0].market_cap_m == 0.0
```

- [ ] **Step 2: 运行新测试，确认 FAIL**

```bash
cd /Users/edy/Desktop/workspace/coin && .venv/bin/pytest tests/test_signal.py::test_market_cap_m_copied_from_match tests/test_signal.py::test_market_cap_m_defaults_to_zero -v
```

预期：2 个 FAIL（`TradeSignal` 无 `market_cap_m` 属性）

- [ ] **Step 3: 在 `scanner/signal.py` 的 `TradeSignal` 中加入 `market_cap_m` 字段**

将 `TradeSignal` dataclass 替换为：

```python
@dataclass
class TradeSignal:
    symbol: str
    price: float
    score: float
    drop_pct: float
    volume_ratio: float
    window_days: int
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    hold_days: int
    signal_type: str = ""
    mode: str = ""
    sl_capped: bool = False
    market_cap_m: float = 0.0
```

- [ ] **Step 4: 在 `generate_signals()` 的 `signals.append(TradeSignal(...))` 中加入 `market_cap_m`**

将 `signals.append(TradeSignal(...))` 替换为：

```python
        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=score,
            drop_pct=m.get("drop_pct", 0),
            volume_ratio=m.get("volume_ratio", 0),
            window_days=m.get("window_days", 0),
            entry_price=entry,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            hold_days=signal_config.hold_days,
            signal_type=signal_type,
            mode=m.get("mode", ""),
            sl_capped=sl_capped,
            market_cap_m=m.get("market_cap_m", 0.0),
        ))
```

- [ ] **Step 5: 运行全量 signal 测试，确认全部通过**

```bash
.venv/bin/pytest tests/test_signal.py -v
```

预期：15 个测试全部 PASS

- [ ] **Step 6: Commit**

```bash
git add scanner/signal.py tests/test_signal.py
git commit -m "feat: add market_cap_m to TradeSignal and copy from match dict"
```

---

## Task 2：scan_results 表迁移 + save_scan() 改接受 list[TradeSignal]

**Files:**
- Modify: `scanner/tracker.py:11-98`
- Create: `tests/test_tracker.py`

- [ ] **Step 1: 新建 `tests/test_tracker.py`，写失败测试**

```python
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest

# 用临时数据库隔离测试，避免污染 scanner.db
import scanner.tracker as tracker_module


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """每个测试使用独立的临时数据库。"""
    db_path = str(tmp_path / "test.db")
    original = tracker_module.DB_PATH
    tracker_module.DB_PATH = db_path
    yield db_path
    tracker_module.DB_PATH = original


def _make_signal(
    symbol="X/USDT",
    price=100.0,
    score=0.75,
    entry_price=97.5,
    stop_loss_price=92.0,
    take_profit_price=106.0,
    signal_type="",
    market_cap_m=500.0,
):
    from scanner.signal import TradeSignal
    return TradeSignal(
        symbol=symbol,
        price=price,
        score=score,
        drop_pct=0.10,
        volume_ratio=1.5,
        window_days=14,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        hold_days=3,
        signal_type=signal_type,
        market_cap_m=market_cap_m,
    )


def test_save_scan_writes_signal_columns(tmp_db):
    """save_scan 应将 entry/sl/tp/signal_type 写入 scan_results。"""
    from scanner.tracker import save_scan
    sig = _make_signal(entry_price=97.5, stop_loss_price=92.625, take_profit_price=109.5, signal_type="底背离")
    scan_id = save_scan([sig], mode="accumulation")

    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM scan_results WHERE scan_id = ?", (scan_id,)).fetchone()
    conn.close()

    assert row is not None
    assert abs(row["entry_price"] - 97.5) < 0.001
    assert abs(row["stop_loss_price"] - 92.625) < 0.001
    assert abs(row["take_profit_price"] - 109.5) < 0.001
    assert row["signal_type"] == "底背离"


def test_save_scan_returns_scan_id(tmp_db):
    """save_scan 应返回正整数 scan_id。"""
    from scanner.tracker import save_scan
    scan_id = save_scan([_make_signal()], mode="divergence")
    assert isinstance(scan_id, int)
    assert scan_id > 0


def test_query_scan_results_returns_new_columns(tmp_db):
    """query_scan_results 返回的 dict 应包含 entry_price / stop_loss_price / take_profit_price / signal_type。"""
    from scanner.tracker import save_scan, query_scan_results
    save_scan([_make_signal(entry_price=97.5, stop_loss_price=92.0, take_profit_price=106.0)], mode="accumulation")
    rows, total = query_scan_results()
    assert total == 1
    row = rows[0]
    assert "entry_price" in row
    assert "stop_loss_price" in row
    assert "take_profit_price" in row
    assert "signal_type" in row
    assert abs(row["entry_price"] - 97.5) < 0.001
```

- [ ] **Step 2: 运行测试，确认 FAIL**

```bash
.venv/bin/pytest tests/test_tracker.py -v
```

预期：3 个测试全部 FAIL（`scan_results` 无新列，`save_scan` 不接受 TradeSignal）

- [ ] **Step 3: 在 `scanner/tracker.py` 的 `_get_conn()` 迁移块中加入 4 列迁移**

在现有迁移块（`# 迁移：positions 表新增列` 之后，`return conn` 之前）加入：

```python
    # 迁移：scan_results 表新增信号列
    sr_existing = {row[1] for row in conn.execute("PRAGMA table_info(scan_results)").fetchall()}
    sr_migrations = [
        ("entry_price",       "REAL"),
        ("stop_loss_price",   "REAL"),
        ("take_profit_price", "REAL"),
        ("signal_type",       "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in sr_migrations:
        if col_name not in sr_existing:
            conn.execute(f"ALTER TABLE scan_results ADD COLUMN {col_name} {col_type}")
    conn.commit()
```

- [ ] **Step 4: 将 `save_scan()` 改为接受 `list[TradeSignal]`**

在文件顶部加入 import（`from scanner.signal import TradeSignal` 会循环导入，改用 TYPE_CHECKING 或直接内联）：

将 `save_scan` 函数替换为：

```python
def save_scan(signals: list, mode: str = "accumulation") -> int:
    """保存一次扫描结果（TradeSignal 列表），返回 scan_id。"""
    conn = _get_conn()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("INSERT INTO scans (scan_time) VALUES (?)", (ts,))
    scan_id = cur.lastrowid
    for s in signals:
        conn.execute(
            "INSERT INTO scan_results "
            "(scan_id, symbol, price, market_cap_m, drop_pct, volume_ratio, window_days, score, mode, "
            "entry_price, stop_loss_price, take_profit_price, signal_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, s.symbol, s.price, getattr(s, "market_cap_m", 0),
             s.drop_pct, s.volume_ratio, s.window_days, s.score, mode,
             s.entry_price, s.stop_loss_price, s.take_profit_price,
             getattr(s, "signal_type", "")),
        )
    conn.commit()
    conn.close()
    return scan_id
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
.venv/bin/pytest tests/test_tracker.py -v
```

预期：3 个测试全部 PASS

- [ ] **Step 6: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -15
```

预期：全部通过

- [ ] **Step 7: Commit**

```bash
git add scanner/tracker.py tests/test_tracker.py
git commit -m "feat: add signal columns to scan_results and update save_scan to accept TradeSignal"
```

---

## Task 3：更新 query_scan_results() + 新增 get_today_scans()

**Files:**
- Modify: `scanner/tracker.py:163-175`（query_scan_results SELECT）
- Test: `tests/test_tracker.py`

- [ ] **Step 1: 在 `tests/test_tracker.py` 末尾追加测试**

```python
def test_query_scan_results_mode_filter(tmp_db):
    """mode 筛选应只返回对应模式的记录。"""
    from scanner.tracker import save_scan, query_scan_results
    save_scan([_make_signal("A/USDT")], mode="accumulation")
    save_scan([_make_signal("B/USDT")], mode="divergence")

    rows, total = query_scan_results(mode="accumulation")
    assert total == 1
    assert rows[0]["symbol"] == "A/USDT"


def test_get_today_scans_returns_latest_scan(tmp_db):
    """get_today_scans 应返回今天该模式最新一次扫描的信号列表。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal("A/USDT"), _make_signal("B/USDT")], mode="accumulation")
    save_scan([_make_signal("C/USDT")], mode="accumulation")  # 第二次扫描，更新

    rows = get_today_scans("accumulation")
    # 应返回最新一次扫描（scan_id 最大），即只有 C/USDT
    assert len(rows) == 1
    assert rows[0]["symbol"] == "C/USDT"


def test_get_today_scans_empty_for_other_mode(tmp_db):
    """get_today_scans 对没有扫描记录的模式返回空列表。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal("A/USDT")], mode="accumulation")

    rows = get_today_scans("divergence")
    assert rows == []


def test_get_today_scans_includes_signal_columns(tmp_db):
    """get_today_scans 返回的 dict 包含 entry_price / stop_loss_price / take_profit_price。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal(entry_price=97.5, stop_loss_price=92.0, take_profit_price=109.0)], mode="divergence")

    rows = get_today_scans("divergence")
    assert len(rows) == 1
    assert abs(rows[0]["entry_price"] - 97.5) < 0.001
    assert abs(rows[0]["stop_loss_price"] - 92.0) < 0.001
    assert abs(rows[0]["take_profit_price"] - 109.0) < 0.001
```

- [ ] **Step 2: 运行新测试，确认 FAIL**

```bash
.venv/bin/pytest tests/test_tracker.py::test_get_today_scans_returns_latest_scan tests/test_tracker.py::test_get_today_scans_empty_for_other_mode tests/test_tracker.py::test_get_today_scans_includes_signal_columns -v
```

预期：3 个 FAIL（`get_today_scans` 未定义）

- [ ] **Step 3: 更新 `query_scan_results()` 的 SELECT 补入 4 列**

将 `query_scan_results()` 里的 SELECT 语句（约第 163-173 行）替换为：

```python
    rows = conn.execute(
        f"""
        SELECT s.scan_time, r.symbol, r.price, r.market_cap_m, r.drop_pct,
               r.volume_ratio, r.window_days, r.score, r.mode,
               r.entry_price, r.stop_loss_price, r.take_profit_price, r.signal_type
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        {where_sql}
        ORDER BY s.scan_time DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()
```

- [ ] **Step 4: 在 `scanner/tracker.py` 末尾（`get_tracked_symbols()` 之后）新增 `get_today_scans()`**

```python
def get_today_scans(mode: str) -> list[dict]:
    """查询今天该模式最新一次扫描（scan_id 最大）的信号列表。"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT MAX(s.id) AS max_scan_id
        FROM scans s
        JOIN scan_results r ON r.scan_id = s.id
        WHERE r.mode = ? AND s.scan_time >= ?
        """,
        (mode, today + " 00:00:00"),
    ).fetchone()
    max_scan_id = row["max_scan_id"] if row else None
    if max_scan_id is None:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT r.symbol, r.price, r.score, r.entry_price,
               r.stop_loss_price, r.take_profit_price, r.signal_type, r.mode
        FROM scan_results r
        WHERE r.scan_id = ?
        ORDER BY r.score DESC
        """,
        (max_scan_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: 运行全量 tracker 测试，确认通过**

```bash
.venv/bin/pytest tests/test_tracker.py -v
```

预期：全部 PASS

- [ ] **Step 6: Commit**

```bash
git add scanner/tracker.py tests/test_tracker.py
git commit -m "feat: update query_scan_results with signal columns and add get_today_scans"
```

---

## Task 4：main.py 三个模式改为先 generate_signals 再 save_scan

**Files:**
- Modify: `main.py:227-233`（accumulation）、`main.py:386-392`（divergence）、`main.py:553-559`（breakout）

注：breakout 模式在 generate_signals 之后还有覆写 stop_loss_price/take_profit_price 的逻辑，save_scan 要在覆写之后调用。

- [ ] **Step 1: 更新 `run()` 中 accumulation 模式的执行顺序**

找到（约 227-237 行，含 `if not signals` 检查）：

```python
    # 保存到数据库
    scan_id = save_scan(ranked)
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return
```

替换为：

```python
    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 保存到数据库（存信号，含点位）
    scan_id = save_scan(signals)
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")
```

- [ ] **Step 2: 更新 `run_divergence()` 中的执行顺序**

找到（约 386-396 行，含 `if not signals` 检查）：

```python
    # 保存到数据库
    scan_id = save_scan(ranked, mode="divergence")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return []
```

替换为：

```python
    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return []

    # 保存到数据库（存信号，含点位）
    scan_id = save_scan(signals, mode="divergence")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")
```

- [ ] **Step 3: 更新 `run_breakout()` 中的执行顺序（save_scan 在 sl/tp 覆写之后）**

找到（约 553-569 行）：

```python
    # 保存到数据库
    scan_id = save_scan(ranked, mode="breakout")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 重算止损止盈（用天量回踩特有的位置）
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        s.stop_loss_price = round(m["pullback_low"] * 0.97, 6)
        s.take_profit_price = round(m["spike_high"], 6)
```

替换为：

```python
    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 重算止损止盈（用天量回踩特有的位置）
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        s.stop_loss_price = round(m["pullback_low"] * 0.97, 6)
        s.take_profit_price = round(m["spike_high"], 6)

    # 保存到数据库（存信号，含覆写后的点位）
    scan_id = save_scan(signals, mode="breakout")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")
```

- [ ] **Step 4: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -15
```

预期：全部通过

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: generate signals before save_scan so signal columns are persisted"
```

---

## Task 5：更新 history_ui/app.py

**Files:**
- Modify: `history_ui/app.py`

- [ ] **Step 1: 将 `history_ui/app.py` 整体替换为**

```python
import os

from flask import Flask, redirect, render_template, request, url_for

from scanner.tracker import (
    get_closed_trades_by_symbol,
    get_today_scans,
    get_tracked_symbols,
    query_scan_results,
)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            accum=get_today_scans("accumulation"),
            div=get_today_scans("divergence"),
            breakout=get_today_scans("breakout"),
        )

    @app.route("/history")
    def history():
        symbol = request.args.get("symbol", "").strip().upper().replace("-", "/")
        mode = request.args.get("mode", "").strip()
        scan_time_from = request.args.get("scan_time_from", "").strip()
        scan_time_to = request.args.get("scan_time_to", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(200, max(1, int(request.args.get("per_page", 50))))
        except ValueError:
            per_page = 50

        rows, total = query_scan_results(
            symbol=symbol or None,
            mode=mode or None,
            scan_time_from=scan_time_from or None,
            scan_time_to=scan_time_to or None,
            page=page,
            per_page=per_page,
        )
        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template(
            "history.html",
            rows=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            per_page_eff=per_page,
            symbol=symbol,
            mode=mode,
            scan_time_from=scan_time_from,
            scan_time_to=scan_time_to,
        )

    @app.route("/search")
    def search():
        symbol = request.args.get("symbol", "").strip().upper().replace("-", "/")
        if not symbol:
            return redirect(url_for("index"))
        return redirect(url_for("coin_detail", symbol_slug=symbol))

    @app.route("/coin/<path:symbol_slug>")
    def coin_detail(symbol_slug: str):
        symbol = symbol_slug.upper()
        scans, _ = query_scan_results(symbol=symbol, per_page=500, max_per_page=500)
        trades = get_closed_trades_by_symbol(symbol)
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

- [ ] **Step 2: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -15
```

预期：全部通过

- [ ] **Step 3: Commit**

```bash
git add history_ui/app.py
git commit -m "feat: rewrite history_ui app with today-scan index and /history filter route"
```

---

## Task 6：更新模板

**Files:**
- Modify: `history_ui/templates/index.html`
- Modify: `history_ui/templates/history.html`
- Modify: `history_ui/templates/base.html`（加 /history 导航入口）

- [ ] **Step 1: 更新 `base.html` 加入历史入口链接**

将 `base.html` 的 `<header>` 替换为：

```html
  <header class="site-header">
    <a class="site-title" href="{{ url_for('index') }}">今日扫描</a>
    <a class="site-nav-link" href="{{ url_for('history') }}">全部历史</a>
    <form class="site-search" action="{{ url_for('search') }}" method="get">
      <input type="text" name="symbol" placeholder="BTC/USDT" autocomplete="off">
      <button type="submit">Go</button>
    </form>
  </header>
```

- [ ] **Step 2: 将 `index.html` 替换为今日扫描三 tab 页**

```html
{% extends "base.html" %}
{% block title %}今日扫描{% endblock %}
{% block content %}
<div class="tab-bar">
  <button class="tab-btn active" data-tab="accum">Accumulation</button>
  <button class="tab-btn" data-tab="div">Divergence</button>
  <button class="tab-btn" data-tab="breakout">Breakout</button>
</div>

{% for tab_id, tab_rows, tab_empty in [
    ("accum",   accum,   "今日暂无 accumulation 信号"),
    ("div",     div,     "今日暂无 divergence 信号"),
    ("breakout",breakout,"今日暂无 breakout 信号"),
] %}
<div class="tab-panel{% if tab_id != 'accum' %} hidden{% endif %}" id="tab-{{ tab_id }}">
  {% if tab_rows %}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>币种</th>
          <th>得分</th>
          <th>入场价</th>
          <th>止损价</th>
          <th>止盈价</th>
          <th>模式</th>
        </tr>
      </thead>
      <tbody>
        {% for row in tab_rows %}
        <tr class="
          {%- if row.score >= 0.75 %} score-high
          {%- elif row.score <= 0.60 %} score-low
          {%- endif %}">
          <td><a class="symbol-link" href="{{ url_for('coin_detail', symbol_slug=row.symbol) }}">{{ row.symbol }}</a></td>
          <td>{{ '%.4f'|format(row.score) }}</td>
          <td>{{ '%.6f'|format(row.entry_price) if row.entry_price else '—' }}</td>
          <td>{{ '%.6f'|format(row.stop_loss_price) if row.stop_loss_price else '—' }}</td>
          <td>{{ '%.6f'|format(row.take_profit_price) if row.take_profit_price else '—' }}</td>
          <td>{{ row.mode }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="muted center">{{ tab_empty }}</p>
  {% endif %}
</div>
{% endfor %}

<script>
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.remove('hidden');
    });
  });
</script>
{% endblock %}
```

- [ ] **Step 3: 将 `history.html` 替换为全量历史筛选页**

```html
{% extends "base.html" %}
{% block title %}全部历史{% endblock %}
{% block content %}
<form class="filters" method="get" action="{{ url_for('history') }}">
  <label>币种 <input type="text" name="symbol" value="{{ symbol }}" placeholder="BTC/USDT" autocomplete="off"></label>
  <label>模式
    <select name="mode">
      <option value="">全部</option>
      {% for m in ["accumulation", "divergence", "breakout"] %}
      <option value="{{ m }}"{% if mode == m %} selected{% endif %}>{{ m }}</option>
      {% endfor %}
    </select>
  </label>
  <label>时间起 <input type="text" name="scan_time_from" value="{{ scan_time_from }}" placeholder="2026-01-01 00:00:00" autocomplete="off"></label>
  <label>时间止 <input type="text" name="scan_time_to" value="{{ scan_time_to }}" placeholder="2026-12-31 23:59:59" autocomplete="off"></label>
  <label>每页 <input type="number" name="per_page" value="{{ per_page_eff }}" min="1" max="200" style="width:5rem"></label>
  <input type="hidden" name="page" value="1">
  <button type="submit">筛选</button>
</form>

<p class="summary">共 <strong>{{ total }}</strong> 条 · 第 {{ page }} / {{ total_pages }} 页</p>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>扫描时间</th>
        <th>币种</th>
        <th>模式</th>
        <th>得分</th>
        <th>入场价</th>
        <th>止损价</th>
        <th>止盈价</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr class="
        {%- if row.score >= 0.75 %} score-high
        {%- elif row.score <= 0.60 %} score-low
        {%- endif %}">
        <td>{{ row.scan_time }}</td>
        <td><a class="symbol-link" href="{{ url_for('coin_detail', symbol_slug=row.symbol) }}">{{ row.symbol }}</a></td>
        <td>{{ row.mode }}</td>
        <td>{{ '%.4f'|format(row.score) }}</td>
        <td>{{ '%.6f'|format(row.entry_price) if row.entry_price else '—' }}</td>
        <td>{{ '%.6f'|format(row.stop_loss_price) if row.stop_loss_price else '—' }}</td>
        <td>{{ '%.6f'|format(row.take_profit_price) if row.take_profit_price else '—' }}</td>
      </tr>
      {% else %}
      <tr><td colspan="7" class="muted center">无数据</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<nav class="pager" aria-label="分页">
  {% if page > 1 %}
  <a class="btn" href="{{ url_for('history', symbol=symbol or none, mode=mode or none, scan_time_from=scan_time_from or none, scan_time_to=scan_time_to or none, page=page-1, per_page=per_page_eff) }}">上一页</a>
  {% endif %}
  {% if page < total_pages %}
  <a class="btn" href="{{ url_for('history', symbol=symbol or none, mode=mode or none, scan_time_from=scan_time_from or none, scan_time_to=scan_time_to or none, page=page+1, per_page=per_page_eff) }}">下一页</a>
  {% endif %}
</nav>
{% endblock %}
```

- [ ] **Step 4: 在 `style.css` 中加入 tab 相关样式**

在 `history_ui/static/style.css` 末尾追加：

```css
/* Tab */
.tab-bar { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
.tab-btn { padding: 0.4rem 1rem; border: 1px solid #444; background: #1e1e1e; color: #ccc; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
.tab-btn.active { background: #2a6496; border-color: #2a6496; color: #fff; }
.tab-panel.hidden { display: none; }
.site-nav-link { color: #aaa; text-decoration: none; font-size: 0.9rem; margin-right: 1rem; }
.site-nav-link:hover { color: #fff; }
```

- [ ] **Step 5: 运行全量测试，确认无回归**

```bash
.venv/bin/pytest tests/ -v 2>&1 | tail -15
```

预期：全部通过

- [ ] **Step 6: Commit**

```bash
git add history_ui/templates/index.html history_ui/templates/history.html history_ui/templates/base.html history_ui/static/style.css
git commit -m "feat: redesign history UI with today-scan tabs and filterable history page"
```

---

## Task 7：全量测试 + push

- [ ] **Step 1: 运行全部测试**

```bash
.venv/bin/pytest tests/ -v
```

预期：全部通过（原有 132 个 + 新增 tracker 测试）

- [ ] **Step 2: 查看提交记录**

```bash
git log --oneline -8
```

- [ ] **Step 3: Push**

```bash
git push origin main
```
