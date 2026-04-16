# Flask → FastAPI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Flask (history_ui/) with FastAPI (api/), achieving full frontend/backend separation. Delete Jinja2 templates.

**Architecture:** Create a new `api/` package with FastAPI app and 3 route modules (scanner, sentiment, portfolio). Migrate all 21 endpoints preserving exact response format. Update Vite proxy target from :5050 to :8000. Delete `history_ui/`.

**Tech Stack:** FastAPI, uvicorn, httpx (TestClient), Vite dev proxy

---

## File Structure

### New Files

```
api/
├── __init__.py              # Package init
├── __main__.py              # uvicorn entry: python -m api
├── app.py                   # FastAPI app factory + CORS + scan state
├── routes/
│   ├── __init__.py
│   ├── scanner.py           # 13 endpoints from history_ui/api.py
│   ├── sentiment.py         # 3 endpoints
│   └── portfolio.py         # 5 endpoints
```

### Modified Files

```
web/vite.config.ts           # Proxy target: 5050 → 8000
ecosystem.config.js          # PM2: python -m api
requirements.txt             # +fastapi,uvicorn,httpx  -flask,flask-cors
tests/test_api_sentiment.py  # Flask TestClient → FastAPI TestClient
tests/test_api_portfolio.py  # Flask TestClient → FastAPI TestClient
tests/e2e/conftest.py        # python -m history_ui → python -m api
cli/__init__.py              # Remove history_ui import in serve if any
```

### Deleted Files

```
history_ui/                  # Entire directory
```

---

## Task 1: FastAPI App Skeleton + Scanner Routes

**Files:**
- Create: `api/__init__.py`, `api/app.py`, `api/__main__.py`, `api/routes/__init__.py`, `api/routes/scanner.py`
- Test: `tests/test_api_scanner.py`

- [ ] **Step 1: Install FastAPI + uvicorn + httpx**

```bash
.venv/bin/pip install fastapi uvicorn httpx
```

- [ ] **Step 2: Update requirements.txt**

Remove `flask>=3.0.0` and `flask-cors>=4.0.0`. Add:
```
fastapi>=0.115.0
uvicorn>=0.30.0
httpx>=0.27.0
```

- [ ] **Step 3: Create api/__init__.py**

```python
"""FastAPI backend for Coin Quant."""
```

- [ ] **Step 4: Create api/app.py**

```python
"""FastAPI application factory."""
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Scan state — process-level singleton (same pattern as old Flask app)
scan_lock = threading.Lock()
scan_state: dict = {"running": False, "started_at": None, "finished_at": None, "error": None}


def create_app() -> FastAPI:
    app = FastAPI(title="Coin Quant API", docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routes.scanner import router as scanner_router
    from api.routes.sentiment import router as sentiment_router
    from api.routes.portfolio import router as portfolio_router

    app.include_router(scanner_router, prefix="/api")
    app.include_router(sentiment_router, prefix="/api")
    app.include_router(portfolio_router, prefix="/api")

    return app
```

- [ ] **Step 5: Create api/__main__.py**

```python
"""Entry point: python -m api"""
import os
import uvicorn

from api.app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 6: Create api/routes/__init__.py**

```python
"""API route modules."""
```

- [ ] **Step 7: Create api/routes/scanner.py**

Read `history_ui/api.py` and migrate all 13 scanner endpoints. Key conversion rules:
- `@api_bp.route("/path")` → `@router.get("/path")`
- `request.args.get("key", default, type=int)` → `key: int = Query(default)`
- `jsonify({...})` → `return {...}`
- `abort(404)` → `raise HTTPException(status_code=404)`
- `<path:symbol>` → `{symbol:path}`

```python
"""Scanner API routes — migrated from Flask."""
import os
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_month,
    compute_stats_by_score_tier,
)
from scanner.tracker import (
    get_active_signals,
    get_closed_trades,
    get_closed_trades_by_symbol,
    get_open_positions,
    get_signal_count_trend,
    get_signal_outcomes,
    get_today_scans,
    query_scan_results,
)

router = APIRouter()


@router.get("/dashboard")
def dashboard():
    accum = get_today_scans("accumulation")
    div = get_today_scans("divergence")
    breakout = get_today_scans("breakout")

    all_signals = accum + div + breakout
    is_today = True
    last_scan_time = None

    if not all_signals:
        is_today = False
        all_signals, last_scan_time = _get_latest_scan_signals()

    all_signals.sort(key=lambda s: s.get("score", 0), reverse=True)

    signal_counts = {"accumulation": 0, "divergence": 0, "breakout": 0}
    for s in all_signals:
        m = s.get("mode", "")
        if m in signal_counts:
            signal_counts[m] += 1

    positions = get_open_positions()
    closed = get_closed_trades()

    today_str = datetime.now().strftime("%Y-%m-%d")
    today_closed = [t for t in closed if (t.get("closed_at") or "")[:10] == today_str]
    today_pnl_pct = sum(t.get("pnl_pct", 0) for t in today_closed)

    overall = compute_stats(closed)
    hit_rate = _compute_7d_hit_rate(closed)

    return {
        "kpi": {
            "today_signals": len(all_signals),
            "active_positions": len(positions),
            "today_pnl_pct": round(today_pnl_pct, 4),
            "today_pnl_count": len(today_closed),
            "win_rate": overall.get("win_rate", 0),
            "total_trades": overall.get("total", 0),
        },
        "top_signals": all_signals[:5],
        "positions": positions,
        "hit_rate_7d": hit_rate,
        "signal_counts": signal_counts,
        "is_today": is_today,
        "last_scan_time": last_scan_time,
    }


@router.get("/signals")
def signals(
    mode: str = Query(""),
    min_score: float | None = Query(None),
    date_from: str = Query(""),
    date_to: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(20),
):
    rows, total = query_scan_results(
        mode=mode.strip() or None,
        scan_time_from=date_from.strip() or None,
        scan_time_to=date_to.strip() or None,
        page=page,
        per_page=per_page,
    )
    if min_score is not None:
        rows = [r for r in rows if r.get("score", 0) >= min_score]
    total_pages = max(1, (total + per_page - 1) // per_page)
    return {"data": rows, "total": total, "page": page, "per_page": per_page, "total_pages": total_pages}


@router.get("/positions")
def positions():
    return {"data": get_open_positions()}


@router.get("/positions/closed")
def positions_closed(page: int = Query(1), per_page: int = Query(20)):
    all_trades = get_closed_trades()
    total = len(all_trades)
    start = (page - 1) * per_page
    page_trades = all_trades[start:start + per_page]
    return {
        "data": page_trades, "total": total, "page": page,
        "per_page": per_page, "total_pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/coin/{symbol:path}")
def coin_detail(symbol: str):
    symbol = symbol.upper()
    scans, total = query_scan_results(symbol=symbol, per_page=500, max_per_page=500)
    trades = get_closed_trades_by_symbol(symbol)
    return {"symbol": symbol, "scans": scans, "trades": trades, "total_scans": total}


@router.get("/performance")
def performance():
    trades = get_closed_trades()
    overall = compute_stats(trades)
    by_mode = compute_stats_by_mode(trades)
    by_score = compute_stats_by_score_tier(trades)
    by_month = compute_stats_by_month(trades)
    cumulative = []
    cum_pnl = 0.0
    sorted_trades = sorted(trades, key=lambda t: t.get("closed_at", ""))
    for t in sorted_trades:
        cum_pnl += t.get("pnl_pct", 0)
        cumulative.append({"date": (t.get("closed_at") or "")[:10], "cumulative_pnl": round(cum_pnl, 4)})
    return {"overall": overall, "by_mode": by_mode, "by_score": by_score, "by_month": by_month, "cumulative_pnl": cumulative}


@router.post("/scan")
def trigger_scan():
    from api.app import scan_lock, scan_state

    if not scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有扫描在进行中")

    def _run():
        scan_state["running"] = True
        scan_state["started_at"] = time.time()
        scan_state["error"] = None
        try:
            from main import load_config, run, run_breakout, run_divergence
            cfg, sig_cfg, *_ = load_config(os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))
            for fn, name in [(run, "accumulation"), (run_divergence, "divergence"), (run_breakout, "breakout")]:
                try:
                    fn(cfg, sig_cfg)
                except Exception as e:
                    scan_state["error"] = f"{name}: {e}"
        finally:
            scan_state["running"] = False
            scan_state["finished_at"] = time.time()
            scan_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.get("/scan/status")
def scan_status():
    from api.app import scan_state
    return dict(scan_state)


@router.get("/klines/{symbol:path}")
def klines(symbol: str, days: int = Query(30)):
    days = min(max(7, days), 180)
    symbol = symbol.upper()
    try:
        from scanner.kline import fetch_klines
        df = fetch_klines(symbol, days=days)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No klines for {symbol}")
        data = []
        for _, row in df.iterrows():
            data.append({
                "timestamp": str(row["timestamp"]), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]),
                "close": float(row["close"]), "volume": float(row["volume"]),
            })
        return {"symbol": symbol, "days": days, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/active")
def active_signals():
    signals = get_active_signals()
    for sig in signals:
        sig["approaching"] = None
        current = sig.get("current_price")
        entry = sig.get("entry_price") or sig.get("price")
        sl = sig.get("stop_loss_price")
        tp = sig.get("take_profit_price")
        if current and entry and sl and tp:
            sl_dist = abs(current - sl) / abs(entry - sl) if abs(entry - sl) > 0 else 1
            tp_dist = abs(tp - current) / abs(tp - entry) if abs(tp - entry) > 0 else 1
            if sl_dist < 0.3:
                sig["approaching"] = "sl"
            elif tp_dist < 0.3:
                sig["approaching"] = "tp"
    return {"data": signals}


@router.get("/signals/outcomes")
def signal_outcomes(days: int = Query(30)):
    return {"data": get_signal_outcomes(days=days)}


@router.get("/signals/trend")
def signal_trend(days: int = Query(7)):
    return {"data": get_signal_count_trend(days=days)}


@router.get("/config")
def get_config():
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    with open(config_path) as f:
        raw = f.read()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = {}
    if data is None:
        data = {}
    if "optimized" in data:
        opt = data["optimized"]
        for k, v in list(opt.items()):
            if not isinstance(v, (int, float, bool, str, type(None))):
                opt[k] = None
    return data


def _get_latest_scan_signals() -> tuple[list[dict], str | None]:
    from scanner.tracker import _get_conn
    conn = _get_conn()
    try:
        row = conn.execute("SELECT scan_time FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return [], None
        last_time = row["scan_time"]
        last_day = last_time[:10]
        all_signals = []
        for mode in ("accumulation", "divergence", "breakout"):
            scan_row = conn.execute(
                "SELECT MAX(s.id) AS max_id FROM scans s JOIN scan_results r ON r.scan_id = s.id "
                "WHERE r.mode = ? AND s.scan_time >= ?", (mode, last_day + " 00:00:00"),
            ).fetchone()
            max_id = scan_row["max_id"] if scan_row else None
            if max_id is None:
                continue
            rows = conn.execute(
                "SELECT r.symbol, r.price, r.score, r.entry_price, r.stop_loss_price, "
                "r.take_profit_price, r.signal_type, r.mode FROM scan_results r "
                "WHERE r.scan_id = ? ORDER BY r.score DESC", (max_id,),
            ).fetchall()
            all_signals.extend(dict(r) for r in rows)
        return all_signals, last_time
    finally:
        conn.close()


def _compute_7d_hit_rate(closed_trades: list[dict]) -> list[dict]:
    today = datetime.now().date()
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_trades = [t for t in closed_trades if (t.get("closed_at") or "")[:10] == day_str]
        day_data = {"date": day_str, "total": len(day_trades)}
        if day_trades:
            day_data["wins"] = sum(1 for t in day_trades if t.get("pnl_pct", 0) > 0)
            day_data["win_rate"] = round(day_data["wins"] / len(day_trades), 4)
        else:
            day_data["wins"] = 0
            day_data["win_rate"] = 0
        result.append(day_data)
    return result
```

- [ ] **Step 8: Create api/routes/sentiment.py**

```python
"""Sentiment API routes — migrated from Flask."""
from fastapi import APIRouter, Query

from sentiment.store import _get_conn

router = APIRouter()


@router.get("/sentiment/latest")
def sentiment_latest():
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT s1.* FROM sentiment_signals s1
            INNER JOIN (SELECT symbol, MAX(id) as max_id FROM sentiment_signals GROUP BY symbol) s2
            ON s1.id = s2.max_id ORDER BY s1.created_at DESC
        """).fetchall()
        return {"signals": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/sentiment/history")
def sentiment_history(symbol: str = Query(""), days: int = Query(7)):
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT date(created_at) as date, AVG(score) as score,
                   CASE WHEN AVG(score) > 0.1 THEN 'bullish'
                        WHEN AVG(score) < -0.1 THEN 'bearish' ELSE 'neutral' END as direction
            FROM sentiment_signals
            WHERE (? = '' OR symbol = ?) AND created_at >= date('now', ? || ' days')
            GROUP BY date(created_at) ORDER BY date ASC
        """, (symbol, symbol, f"-{days}")).fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/sentiment/items")
def sentiment_items(
    source: str = Query(""),
    symbol: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(20),
):
    offset = (page - 1) * per_page
    conn = _get_conn()
    try:
        clauses, params = [], []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(f"SELECT COUNT(*) FROM sentiment_items {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM sentiment_items {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "per_page": per_page}
    finally:
        conn.close()
```

- [ ] **Step 9: Create api/routes/portfolio.py**

```python
"""Portfolio API routes — migrated from Flask."""
from fastapi import APIRouter, HTTPException, Query

from portfolio.store import _get_conn, query_latest_weights, query_nav_history, query_risk_events

router = APIRouter()


@router.get("/portfolio/status")
def portfolio_status():
    weights = query_latest_weights()
    nav_rows = query_nav_history(limit=1)
    nav = nav_rows[0]["nav"] if nav_rows else 0.0
    hwm = nav_rows[0].get("hwm", nav_rows[0].get("high_water_mark", 0.0)) if nav_rows else 0.0
    drawdown = (hwm - nav) / hwm if hwm > 0 else 0.0
    return {
        "weights": weights, "nav": nav, "high_water_mark": hwm,
        "drawdown_pct": round(drawdown, 4), "portfolio_halted": drawdown > 0.05,
        "halted_strategies": [],
    }


@router.get("/portfolio/nav-history")
def portfolio_nav_history(days: int = Query(90)):
    history = query_nav_history(limit=days)
    history.reverse()
    return {"history": history}


@router.get("/portfolio/weights-history")
def portfolio_weights_history():
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT date, strategy_id, weight FROM strategy_weights ORDER BY date ASC").fetchall()
        by_date: dict = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = {"date": d, "weights": {}}
            by_date[d]["weights"][r["strategy_id"]] = r["weight"]
        return {"history": list(by_date.values())}
    finally:
        conn.close()


@router.get("/portfolio/risk-events")
def portfolio_risk_events(limit: int = Query(20)):
    return {"events": query_risk_events(limit=limit)}


@router.post("/portfolio/rebalance")
def portfolio_rebalance():
    try:
        from main import load_config, run_portfolio_rebalance
        _, _, _, _, _, portfolio_config = load_config()
        run_portfolio_rebalance(portfolio_config)
        return {"success": True, "weights": query_latest_weights()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 10: Write basic smoke test**

```python
# tests/test_api_scanner.py
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("COIN_DB_PATH", db_path)
    # Ensure tables exist
    from scanner.tracker import _get_conn
    conn = _get_conn()
    conn.close()
    from api.app import create_app
    app = create_app()
    return TestClient(app)


class TestScannerEndpoints:
    def test_dashboard(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "kpi" in data
        assert "top_signals" in data

    def test_signals(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_positions(self, client):
        resp = client.get("/api/positions")
        assert resp.status_code == 200

    def test_positions_closed(self, client):
        resp = client.get("/api/positions/closed")
        assert resp.status_code == 200

    def test_performance(self, client):
        resp = client.get("/api/performance")
        assert resp.status_code == 200
        assert "overall" in resp.json()

    def test_scan_status(self, client):
        resp = client.get("/api/scan/status")
        assert resp.status_code == 200
        assert "running" in resp.json()

    def test_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
```

- [ ] **Step 11: Run tests**

```bash
.venv/bin/pytest tests/test_api_scanner.py -v
```

- [ ] **Step 12: Commit**

```bash
git add api/ tests/test_api_scanner.py requirements.txt
git commit -m "feat(api): create FastAPI app with scanner, sentiment, portfolio routes"
```

---

## Task 2: Migrate API Tests to FastAPI TestClient

**Files:**
- Modify: `tests/test_api_sentiment.py`
- Modify: `tests/test_api_portfolio.py`

- [ ] **Step 1: Update test_api_sentiment.py**

Replace the Flask test client fixture with FastAPI TestClient:

```python
# Change the fixture from:
#   from history_ui.app import create_app
#   app = create_app()
#   app.config["TESTING"] = True
#   return app.test_client()
# To:
from fastapi.testclient import TestClient
from api.app import create_app

@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("COIN_DB_PATH", db_path)
    # ... seed data same as before ...
    app = create_app()
    return TestClient(app)
```

Also update response parsing: `resp.get_json()` → `resp.json()`

- [ ] **Step 2: Update test_api_portfolio.py**

Same changes as above.

- [ ] **Step 3: Run all API tests**

```bash
.venv/bin/pytest tests/test_api_scanner.py tests/test_api_sentiment.py tests/test_api_portfolio.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_sentiment.py tests/test_api_portfolio.py
git commit -m "refactor(tests): migrate API tests from Flask to FastAPI TestClient"
```

---

## Task 3: Update Vite Proxy + E2E Tests + ecosystem.config.js

**Files:**
- Modify: `web/vite.config.ts`
- Modify: `tests/e2e/conftest.py`
- Modify: `ecosystem.config.js`

- [ ] **Step 1: Update vite.config.ts proxy target**

Change proxy target from `http://127.0.0.1:5050` to `http://127.0.0.1:8000`:

```typescript
proxy: {
  "/api": {
    target: "http://127.0.0.1:8000",
    changeOrigin: true,
  },
},
```

- [ ] **Step 2: Update E2E conftest.py**

Change server startup command and port env vars:

```python
# Change:
#   env["HISTORY_UI_PORT"] = str(port)
#   env["HISTORY_UI_HOST"] = "127.0.0.1"
#   proc = subprocess.Popen([".venv/bin/python", "-m", "history_ui"], ...)
# To:
env["API_PORT"] = str(port)
env["API_HOST"] = "127.0.0.1"
proc = subprocess.Popen([".venv/bin/python", "-m", "api"], env=env, ...)
```

Note: The E2E tests navigate to `/app/` which was served by Flask's SPA route. With FastAPI, we need to either:
- Add a static file mount for `web/dist/` in FastAPI, OR
- Skip E2E tests for now (they test the React SPA which needs a running frontend)

Since we're doing full separation, add a minimal static file mount to FastAPI for backward compatibility:

```python
# In api/app.py, add at the end of create_app():
import os
spa_dir = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
if os.path.isdir(spa_dir):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    @app.get("/app/{path:path}")
    @app.get("/app/")
    async def spa(path: str = ""):
        file_path = os.path.join(spa_dir, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        index = os.path.join(spa_dir, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return {"error": "React SPA not built. Run: cd web && npm run build"}
```

- [ ] **Step 3: Update ecosystem.config.js**

Read the existing file, then update the script command from `python -m history_ui` to `python -m api`.

- [ ] **Step 4: Run E2E tests**

```bash
.venv/bin/pytest tests/e2e/ -v
```

- [ ] **Step 5: Commit**

```bash
git add web/vite.config.ts tests/e2e/conftest.py ecosystem.config.js api/app.py
git commit -m "refactor: update vite proxy, E2E tests, and PM2 config for FastAPI"
```

---

## Task 4: Delete history_ui + Cleanup

**Files:**
- Delete: `history_ui/` (entire directory)
- Modify: `CLAUDE.md`
- Modify: any files that import from `history_ui`

- [ ] **Step 1: Search for history_ui imports**

```bash
grep -r "history_ui" --include="*.py" . | grep -v __pycache__ | grep -v .git
```

Fix any remaining references (e.g., in `main.py`, `cli/__init__.py`).

- [ ] **Step 2: Delete history_ui directory**

```bash
git rm -r history_ui/
```

- [ ] **Step 3: Update CLAUDE.md**

Replace:
```
# Scan history web UI (read-only browser for scanner.db scan_results)
.venv/bin/python -m history_ui
```

With:
```
# API server (FastAPI)
.venv/bin/python -m api                            # http://127.0.0.1:8000 (API_HOST / API_PORT)
                                                    # OpenAPI docs: http://127.0.0.1:8000/docs

# Frontend dev server (Vite)
cd web && npm run dev                               # http://127.0.0.1:5173 (proxies /api → :8000)
```

Update architecture section: replace `history_ui/` references with `api/` references.

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/ --ignore=tests/e2e -v
```

Verify no import errors from deleted history_ui.

- [ ] **Step 5: Run E2E tests**

```bash
.venv/bin/pytest tests/e2e/ -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete history_ui, complete Flask→FastAPI migration"
```
