# 信号成功率追踪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关仓时自动记录退出信息，提供多维度成功率分析（按模式 / 评分 / 时间），CLI 表格 + JSON 导出。

**Architecture:** 扩展 `positions` 表加 5 列（exit_price, pnl, pnl_pct, exit_reason, mode）；修改 `monitor.py` 关仓时从 TP/SL 订单推断退出信息并算 PnL；新建 `scanner/stats.py` 做聚合统计；`main.py` 加 `--stats` 入口。

**Tech Stack:** Python 3.13, SQLite, tabulate, pytest

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `scanner/tracker.py` | 修改 | positions 表迁移 + `close_position()` 扩展 + `get_order_by_id()` + `get_closed_trades()` |
| `scanner/trader/executor.py` | 修改 | `save_position()` 调用传入 `mode` |
| `scanner/trader/monitor.py` | 修改 | `check_positions()` 推断 exit_reason/price，算 PnL |
| `scanner/stats.py` | 新建 | `compute_stats()` + 分组统计 + 格式化 + JSON 导出 |
| `main.py` | 修改 | `--stats` / `--json-only` argparse + `run_stats()` |
| `tests/test_trader_db.py` | 修改 | `close_position` 新参数测试 |
| `tests/test_stats.py` | 新建 | stats 模块全部函数的单元测试 |

---

### Task 1: 扩展 positions 表 + tracker 函数

**Files:**
- Modify: `scanner/tracker.py`
- Test: `tests/test_trader_db.py`

- [ ] **Step 1: 写 close_position 扩展参数的失败测试**

在 `tests/test_trader_db.py` 的 `TestPositions` 类中添加：

```python
def test_close_position_with_exit_info(self):
    tracker.save_position(
        symbol="ETH/USDT", side="long", entry_price=3000.0,
        size=1.0, leverage=5, score=0.7, mode="divergence",
    )
    tracker.close_position(
        "ETH/USDT",
        exit_price=3240.0,
        pnl=240.0,
        pnl_pct=0.08,
        exit_reason="tp",
    )
    positions = tracker.get_open_positions()
    assert len(positions) == 0

    trades = tracker.get_closed_trades()
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_price"] == 3240.0
    assert t["pnl"] == 240.0
    assert abs(t["pnl_pct"] - 0.08) < 0.001
    assert t["exit_reason"] == "tp"
    assert t["mode"] == "divergence"

def test_close_position_backward_compat(self):
    """无 exit 参数时仍正常工作（兼容旧调用）。"""
    tracker.save_position(
        symbol="A/USDT", side="long", entry_price=1.0,
        size=1.0, leverage=5, score=0.7,
    )
    tracker.close_position("A/USDT")
    positions = tracker.get_open_positions()
    assert len(positions) == 0

def test_get_order_by_id(self):
    tracker.save_order(
        order_id="TP001", symbol="BTC/USDT", side="sell",
        order_type="TAKE_PROFIT_MARKET", price=55000.0, amount=0.1,
    )
    order = tracker.get_order_by_id("TP001")
    assert order is not None
    assert order["symbol"] == "BTC/USDT"
    assert tracker.get_order_by_id("NONEXIST") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_trader_db.py -v`
Expected: FAIL — `save_position()` 不接受 `mode` 参数；`close_position()` 不接受 exit 参数；`get_closed_trades` 和 `get_order_by_id` 不存在。

- [ ] **Step 3: 修改 tracker.py — 表迁移 + 函数扩展**

在 `_get_conn()` 的 `positions` CREATE TABLE 后面，加迁移逻辑（用 `PRAGMA table_info` 检查列是否存在）：

```python
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # ... 现有 CREATE TABLE 语句不变 ...
    conn.commit()

    # 迁移：positions 表新增列（兼容已有数据库）
    existing = {row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
    migrations = [
        ("exit_price", "REAL"),
        ("pnl", "REAL"),
        ("pnl_pct", "REAL"),
        ("exit_reason", "TEXT"),
        ("mode", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
    conn.commit()
    return conn
```

修改 `save_position()` 加 `mode` 参数：

```python
def save_position(
    symbol: str,
    side: str,
    entry_price: float,
    size: float,
    leverage: int,
    score: float,
    tp_order_id: str | None = None,
    sl_order_id: str | None = None,
    mode: str = "",
) -> int:
    """保存一条持仓记录，返回本地 id。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO positions (symbol, side, entry_price, size, leverage, score, tp_order_id, sl_order_id, status, opened_at, mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (symbol, side, entry_price, size, leverage, score, tp_order_id, sl_order_id, now, mode),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id
```

修改 `close_position()` 接受 exit 参数：

```python
def close_position(
    symbol: str,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_pct: float | None = None,
    exit_reason: str | None = None,
) -> None:
    """关闭某币种的持仓，可附带退出信息。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE positions SET status = 'closed', closed_at = ?, "
        "exit_price = ?, pnl = ?, pnl_pct = ?, exit_reason = ? "
        "WHERE symbol = ? AND status = 'open'",
        (now, exit_price, pnl, pnl_pct, exit_reason, symbol),
    )
    conn.commit()
    conn.close()
```

新增 `get_order_by_id()`：

```python
def get_order_by_id(order_id: str) -> dict | None:
    """按 order_id 查询单条订单。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
```

新增 `get_closed_trades()`：

```python
def get_closed_trades() -> list[dict]:
    """查询所有已关仓且有 pnl 数据的持仓。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status = 'closed' AND pnl_pct IS NOT NULL "
        "ORDER BY closed_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_trader_db.py -v`
Expected: 全部 PASS（9 个测试，包含 3 个新增）

- [ ] **Step 5: 提交**

```bash
git add scanner/tracker.py tests/test_trader_db.py
git commit -m "feat: extend positions table with exit tracking columns"
```

---

### Task 2: executor.py 传入 mode

**Files:**
- Modify: `scanner/trader/executor.py:144-154`

- [ ] **Step 1: 修改 executor.py 的 save_position 调用**

在 `execute_trade()` 函数末尾（约第 145 行），修改 `save_position()` 调用，加入 `mode=signal.mode`：

```python
    # 4. 记录持仓
    save_position(
        symbol=symbol,
        side="short" if is_short else "long",
        entry_price=signal.entry_price,
        size=amount,
        leverage=leverage,
        score=signal.score,
        tp_order_id=tp_order_id,
        sl_order_id=sl_order_id,
        mode=signal.mode,
    )
```

- [ ] **Step 2: 跑已有测试确认无回归**

Run: `.venv/bin/pytest tests/test_trader_db.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add scanner/trader/executor.py
git commit -m "feat: pass signal mode to save_position for tracking"
```

---

### Task 3: monitor.py 关仓时记录退出信息

**Files:**
- Modify: `scanner/trader/monitor.py:103-126`

- [ ] **Step 1: 修改 monitor.py 的 import**

在文件头部 import 中加入 `get_order_by_id`：

```python
from scanner.tracker import (
    get_open_orders,
    get_open_positions,
    update_order_status,
    close_position,
    save_order,
    get_order_by_id,
)
```

- [ ] **Step 2: 重写 check_positions() 函数**

替换 `check_positions()` 函数（约第 103-126 行）：

```python
def _infer_exit(pos: dict, exchange: ccxt.binanceusdm) -> dict:
    """推断退出原因和价格。返回 {exit_price, exit_reason, pnl, pnl_pct}。"""
    entry_price = pos["entry_price"]
    size = pos["size"]
    is_short = pos["side"] == "short"

    # 查 TP 订单
    if pos.get("tp_order_id"):
        tp_order = get_order_by_id(pos["tp_order_id"])
        if tp_order and tp_order["status"] == "filled":
            exit_price = tp_order["price"]
            pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
            return {
                "exit_price": exit_price,
                "exit_reason": "tp",
                "pnl_pct": round(pnl_pct, 6),
                "pnl": round(pnl_pct * entry_price * size, 4),
            }

    # 查 SL 订单
    if pos.get("sl_order_id"):
        sl_order = get_order_by_id(pos["sl_order_id"])
        if sl_order and sl_order["status"] == "filled":
            exit_price = sl_order["price"]
            pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
            return {
                "exit_price": exit_price,
                "exit_reason": "sl",
                "pnl_pct": round(pnl_pct, 6),
                "pnl": round(pnl_pct * entry_price * size, 4),
            }

    # 手动平仓：取当前市价
    try:
        ticker = exchange.fetch_ticker(pos["symbol"])
        exit_price = ticker["last"]
    except Exception:
        exit_price = entry_price  # 取不到就用入场价（PnL=0）

    pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
    return {
        "exit_price": exit_price,
        "exit_reason": "manual",
        "pnl_pct": round(pnl_pct, 6),
        "pnl": round(pnl_pct * entry_price * size, 4),
    }


def check_positions(exchange: ccxt.binanceusdm) -> None:
    """检查持仓的 TPSL 是否已触发，更新已平仓的记录。"""
    positions = get_open_positions()
    if not positions:
        return

    try:
        exchange_positions = exchange.fetch_positions()
    except Exception as e:
        logger.error("查询交易所持仓失败: %s", e)
        return

    # 交易所当前有仓位的 symbol 集合
    active_symbols = set()
    for p in exchange_positions:
        if float(p.get("contracts", 0)) > 0:
            active_symbols.add(p["symbol"])

    # DB 里标记为 open 但交易所已无仓位 → 已平仓
    for pos in positions:
        if pos["symbol"] not in active_symbols:
            exit_info = _infer_exit(pos, exchange)
            close_position(
                pos["symbol"],
                exit_price=exit_info["exit_price"],
                pnl=exit_info["pnl"],
                pnl_pct=exit_info["pnl_pct"],
                exit_reason=exit_info["exit_reason"],
            )
            reason_label = {"tp": "止盈", "sl": "止损", "manual": "手动"}[exit_info["exit_reason"]]
            logger.info(
                "[%s] 仓位已平仓（%s）exit=%.4f pnl=%.2f%%",
                pos["symbol"], reason_label, exit_info["exit_price"], exit_info["pnl_pct"] * 100,
            )
```

- [ ] **Step 3: 跑已有测试确认无回归**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add scanner/trader/monitor.py
git commit -m "feat: infer exit reason and compute PnL on position close"
```

---

### Task 4: 新建 scanner/stats.py — compute_stats

**Files:**
- Create: `scanner/stats.py`
- Create: `tests/test_stats.py`

- [ ] **Step 1: 写 compute_stats 的失败测试**

创建 `tests/test_stats.py`：

```python
from scanner.stats import compute_stats


def test_compute_stats_basic():
    """基本统计：3 笔交易，2 赢 1 亏。"""
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0},
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": -0.03, "pnl": -30.0},
    ]
    s = compute_stats(trades)
    assert s["total"] == 3
    assert s["wins"] == 2
    assert abs(s["win_rate"] - 2 / 3) < 0.01
    assert abs(s["avg_pnl_pct"] - (0.08 + 0.05 - 0.03) / 3) < 0.001
    assert abs(s["profit_factor"] - 130 / 30) < 0.01
    assert s["max_gain"] == 0.08
    assert s["max_loss"] == -0.03


def test_compute_stats_empty():
    """空列表返回零值。"""
    s = compute_stats([])
    assert s["total"] == 0
    assert s["win_rate"] == 0
    assert s["profit_factor"] == 0


def test_compute_stats_all_wins():
    """全赢时 profit_factor 用总盈利代替（除零保护）。"""
    trades = [
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": 0.10, "pnl": 100.0},
    ]
    s = compute_stats(trades)
    assert s["win_rate"] == 1.0
    assert s["profit_factor"] == 150.0
    assert s["max_loss"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: FAIL — `scanner.stats` 不存在

- [ ] **Step 3: 实现 compute_stats**

创建 `scanner/stats.py`：

```python
"""信号成功率统计分析。"""


def compute_stats(trades: list[dict]) -> dict:
    """从已关仓交易列表计算统计指标。"""
    if not trades:
        return {
            "total": 0, "wins": 0, "win_rate": 0,
            "avg_pnl_pct": 0, "profit_factor": 0,
            "max_gain": 0, "max_loss": 0,
        }

    total = len(trades)
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = wins / total

    pnl_pcts = [t["pnl_pct"] for t in trades]
    avg_pnl_pct = sum(pnl_pcts) / total

    total_gain = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = total_gain / total_loss if total_loss > 0 else total_gain

    return {
        "total": total,
        "wins": wins,
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(avg_pnl_pct, 6),
        "profit_factor": round(profit_factor, 2),
        "max_gain": max(pnl_pcts),
        "max_loss": min(pnl_pcts) if min(pnl_pcts) < 0 else 0,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stats.py::test_compute_stats_basic tests/test_stats.py::test_compute_stats_empty tests/test_stats.py::test_compute_stats_all_wins -v`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add scanner/stats.py tests/test_stats.py
git commit -m "feat: add compute_stats for trade performance analysis"
```

---

### Task 5: stats.py — 分组统计函数

**Files:**
- Modify: `scanner/stats.py`
- Modify: `tests/test_stats.py`

- [ ] **Step 1: 写分组统计的失败测试**

在 `tests/test_stats.py` 末尾追加：

```python
from scanner.stats import compute_stats_by_mode, compute_stats_by_score_tier, compute_stats_by_month


def test_compute_stats_by_mode():
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0, "mode": "divergence"},
        {"pnl_pct": -0.03, "pnl": -30.0, "mode": "divergence"},
        {"pnl_pct": 0.05, "pnl": 50.0, "mode": "accumulation"},
    ]
    by_mode = compute_stats_by_mode(trades)
    assert "divergence" in by_mode
    assert "accumulation" in by_mode
    assert by_mode["divergence"]["total"] == 2
    assert by_mode["accumulation"]["total"] == 1
    assert by_mode["accumulation"]["win_rate"] == 1.0


def test_compute_stats_by_score_tier():
    trades = [
        {"pnl_pct": 0.10, "pnl": 100.0, "score": 0.85},
        {"pnl_pct": 0.05, "pnl": 50.0, "score": 0.75},
        {"pnl_pct": -0.02, "pnl": -20.0, "score": 0.65},
    ]
    by_score = compute_stats_by_score_tier(trades)
    assert by_score["0.8+"]["total"] == 1
    assert by_score["0.8+"]["win_rate"] == 1.0
    assert by_score["0.7-0.8"]["total"] == 1
    assert by_score["0.6-0.7"]["total"] == 1


def test_compute_stats_by_month():
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0, "closed_at": "2026-04-05 10:00:00"},
        {"pnl_pct": -0.03, "pnl": -30.0, "closed_at": "2026-04-10 10:00:00"},
        {"pnl_pct": 0.05, "pnl": 50.0, "closed_at": "2026-03-20 10:00:00"},
    ]
    by_month = compute_stats_by_month(trades)
    assert "2026-04" in by_month
    assert "2026-03" in by_month
    assert by_month["2026-04"]["total"] == 2
    assert by_month["2026-03"]["total"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: 3 个新测试 FAIL

- [ ] **Step 3: 实现分组统计函数**

在 `scanner/stats.py` 末尾追加：

```python
def _group_by(trades: list[dict], key_fn) -> dict[str, list[dict]]:
    """按 key_fn 分组。"""
    groups: dict[str, list[dict]] = {}
    for t in trades:
        k = key_fn(t)
        groups.setdefault(k, []).append(t)
    return groups


def compute_stats_by_mode(trades: list[dict]) -> dict[str, dict]:
    """按 mode 分组计算统计。"""
    groups = _group_by(trades, lambda t: t.get("mode", ""))
    return {mode: compute_stats(group) for mode, group in sorted(groups.items())}


def compute_stats_by_score_tier(trades: list[dict]) -> dict[str, dict]:
    """按评分区间分组: 0.6-0.7, 0.7-0.8, 0.8+。"""
    def tier(t):
        s = t.get("score", 0)
        if s >= 0.8:
            return "0.8+"
        if s >= 0.7:
            return "0.7-0.8"
        return "0.6-0.7"

    groups = _group_by(trades, tier)
    order = ["0.8+", "0.7-0.8", "0.6-0.7"]
    return {k: compute_stats(groups.get(k, [])) for k in order if k in groups}


def compute_stats_by_month(trades: list[dict]) -> dict[str, dict]:
    """按 YYYY-MM 分组计算统计。"""
    def month_key(t):
        return t.get("closed_at", "")[:7]

    groups = _group_by(trades, month_key)
    return {month: compute_stats(group) for month, group in sorted(groups.items(), reverse=True)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: 全部 6 PASS

- [ ] **Step 5: 提交**

```bash
git add scanner/stats.py tests/test_stats.py
git commit -m "feat: add grouped stats by mode, score tier, and month"
```

---

### Task 6: stats.py — 格式化输出 + JSON 导出

**Files:**
- Modify: `scanner/stats.py`
- Modify: `tests/test_stats.py`

- [ ] **Step 1: 写格式化和导出的失败测试**

在 `tests/test_stats.py` 末尾追加：

```python
import json
import os

from scanner.stats import format_stats_report, export_stats_json


def test_format_stats_report_contains_key_info():
    overall = {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}
    by_mode = {"divergence": {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}}
    by_score = {"0.8+": {"total": 5, "wins": 4, "win_rate": 0.8, "avg_pnl_pct": 0.04, "profit_factor": 2.0, "max_gain": 0.1, "max_loss": -0.02}}
    by_month = {"2026-04": {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}}

    report = format_stats_report(overall, by_mode, by_score, by_month)
    assert "70.0%" in report
    assert "divergence" in report
    assert "0.8+" in report
    assert "2026-04" in report


def test_export_stats_json(tmp_path):
    overall = {"total": 5, "wins": 3, "win_rate": 0.6, "avg_pnl_pct": 0.02, "profit_factor": 1.2, "max_gain": 0.05, "max_loss": -0.03}
    trades = [{"symbol": "BTC/USDT", "pnl_pct": 0.05}]

    path = export_stats_json(overall, {}, {}, {}, trades=trades, output_dir=str(tmp_path))
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["overall"]["total"] == 5
    assert len(data["trades"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_stats.py::test_format_stats_report_contains_key_info tests/test_stats.py::test_export_stats_json -v`
Expected: FAIL

- [ ] **Step 3: 实现格式化和导出**

在 `scanner/stats.py` 顶部添加 import：

```python
import json
import os
from datetime import datetime
```

在文件末尾追加：

```python
def format_stats_report(
    overall: dict,
    by_mode: dict[str, dict],
    by_score: dict[str, dict],
    by_month: dict[str, dict],
) -> str:
    """格式化为终端表格字符串。"""
    lines = []
    lines.append("=== 信号成功率统计 ===")
    lines.append(
        f"总交易: {overall['total']}  |  "
        f"胜率: {overall['win_rate'] * 100:.1f}%  |  "
        f"平均盈亏: {overall['avg_pnl_pct'] * 100:+.1f}%  |  "
        f"盈亏比: {overall['profit_factor']:.2f}"
    )

    if by_mode:
        lines.append("")
        lines.append("[按模式]")
        lines.append(f"{'模式':<16} {'交易数':>6} {'胜率':>8} {'平均盈亏':>10} {'盈亏比':>8}")
        for mode, s in by_mode.items():
            lines.append(
                f"{mode:<16} {s['total']:>6} {s['win_rate'] * 100:>7.1f}% {s['avg_pnl_pct'] * 100:>+9.1f}% {s['profit_factor']:>8.2f}"
            )

    if by_score:
        lines.append("")
        lines.append("[按评分]")
        lines.append(f"{'评分区间':<16} {'交易数':>6} {'胜率':>8} {'平均盈亏':>10} {'盈亏比':>8}")
        for tier, s in by_score.items():
            lines.append(
                f"{tier:<16} {s['total']:>6} {s['win_rate'] * 100:>7.1f}% {s['avg_pnl_pct'] * 100:>+9.1f}% {s['profit_factor']:>8.2f}"
            )

    if by_month:
        lines.append("")
        lines.append("[按月份]")
        lines.append(f"{'月份':<16} {'交易数':>6} {'胜率':>8} {'平均盈亏':>10} {'盈亏比':>8}")
        for month, s in by_month.items():
            lines.append(
                f"{month:<16} {s['total']:>6} {s['win_rate'] * 100:>7.1f}% {s['avg_pnl_pct'] * 100:>+9.1f}% {s['profit_factor']:>8.2f}"
            )

    return "\n".join(lines)


def export_stats_json(
    overall: dict,
    by_mode: dict[str, dict],
    by_score: dict[str, dict],
    by_month: dict[str, dict],
    trades: list[dict] | None = None,
    output_dir: str = "results",
) -> str:
    """导出为 JSON 并写入 output_dir，返回文件路径。"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"stats_{ts}.json")

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall": overall,
        "by_mode": by_mode,
        "by_score_tier": by_score,
        "by_month": by_month,
        "trades": trades or [],
    }
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: 全部 8 PASS

- [ ] **Step 5: 提交**

```bash
git add scanner/stats.py tests/test_stats.py
git commit -m "feat: add stats formatting and JSON export"
```

---

### Task 7: main.py — --stats CLI 入口

**Files:**
- Modify: `main.py:15,1000-1084`

- [ ] **Step 1: 添加 import**

在 `main.py` 顶部 import 区域（约第 15 行后）添加：

```python
from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_score_tier,
    compute_stats_by_month,
    format_stats_report,
    export_stats_json,
)
from scanner.tracker import get_closed_trades
```

注意：`get_closed_trades` 需要加到现有的 tracker import 行（第 14 行），改为：

```python
from scanner.tracker import save_scan, get_tracked_symbols, get_history, get_closed_trades
```

然后 stats 单独 import：

```python
from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_score_tier,
    compute_stats_by_month,
    format_stats_report,
    export_stats_json,
)
```

- [ ] **Step 2: 添加 run_stats() 函数**

在 `main.py` 的 `main()` 函数之前添加：

```python
def run_stats(json_only: bool = False) -> None:
    """输出信号成功率统计。"""
    trades = get_closed_trades()
    if not trades:
        print("暂无已关仓交易数据。")
        return

    overall = compute_stats(trades)
    by_mode = compute_stats_by_mode(trades)
    by_score = compute_stats_by_score_tier(trades)
    by_month = compute_stats_by_month(trades)

    if not json_only:
        print(format_stats_report(overall, by_mode, by_score, by_month))

    path = export_stats_json(overall, by_mode, by_score, by_month, trades=trades)
    print(f"\n[导出] {path}")
```

- [ ] **Step 3: 添加 argparse 参数**

在 `main()` 函数的 argparse 区域（`--serve` 之后），添加两个参数：

```python
    parser.add_argument(
        "--stats",
        action="store_true",
        help="查看信号成功率统计（按模式/评分/月份）",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="与 --stats 联用：仅导出 JSON，不打印表格",
    )
```

- [ ] **Step 4: 添加路由分支**

在 `main()` 函数的 `if args.serve:` 分支之后、`elif args.track:` 之前，插入：

```python
    elif args.stats:
        run_stats(json_only=args.json_only)
```

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add main.py
git commit -m "feat: add --stats CLI for signal success rate analysis"
```

---

## 自查

- **Spec 覆盖**: positions 新增 5 列 ✓、关仓推断退出 ✓、多维度统计 ✓、CLI + JSON ✓
- **占位符扫描**: 无 TBD/TODO
- **类型一致性**: `compute_stats` 入参 `list[dict]`、返回 `dict`；`close_position` 新参数 `exit_price/pnl/pnl_pct/exit_reason` 在 tracker.py、monitor.py、test 中签名一致；`save_position` 新参数 `mode` 在 tracker.py 和 executor.py 中一致
