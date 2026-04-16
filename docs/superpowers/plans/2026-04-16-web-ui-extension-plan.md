# Web UI Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the React SPA with Dashboard, Sentiment, and Portfolio pages, backed by new Flask API endpoints, verified with Playwright E2E tests.

**Architecture:** New Flask API endpoints in `history_ui/api.py` query sentiment and portfolio SQLite tables. New React pages consume these APIs following existing patterns (useState/useEffect hooks, Recharts charts, Tailwind styling). Playwright tests verify page rendering and core interactions.

**Tech Stack:** Flask (existing), React 19, TypeScript, Recharts, Tailwind CSS v4, Playwright (pytest-playwright)

---

## File Structure

### Backend (Modify)

```
history_ui/api.py            # Add sentiment + portfolio API endpoints
```

### Frontend (New)

```
web/src/api/sentiment.ts     # Sentiment API client functions
web/src/api/portfolio.ts     # Portfolio API client functions
web/src/pages/DashboardV2.tsx    #综合 Dashboard（替换现有 Dashboard）
web/src/pages/SentimentPage.tsx  # 舆情仪表盘
web/src/pages/PortfolioPage.tsx  # 组合管理面板
web/src/components/StatCard.tsx          # 通用数值卡片
web/src/components/SentimentTable.tsx    # 情绪信号表格
web/src/components/SentimentChart.tsx    # 情绪趋势折线图
web/src/components/SentimentItems.tsx    # 原始条目列表
web/src/components/WeightsPieChart.tsx   # 策略权重饼图
web/src/components/NavChart.tsx          # NAV 曲线
web/src/components/RiskStatus.tsx        # 风控状态 + 事件
```

### Frontend (Modify)

```
web/src/App.tsx              # Add new routes
web/src/components/Layout.tsx # Add nav items
```

### E2E Tests (New)

```
tests/e2e/conftest.py        # Fixtures: seed DB, start server
tests/e2e/test_dashboard.py  # Dashboard smoke + functional
tests/e2e/test_sentiment.py  # Sentiment smoke + functional
tests/e2e/test_portfolio.py  # Portfolio smoke + functional
```

---

## Task 1: Backend API — Sentiment Endpoints

**Files:**
- Modify: `history_ui/api.py`
- Test: `tests/test_api_sentiment.py`

- [ ] **Step 1: Write failing tests for sentiment API endpoints**

```python
# tests/test_api_sentiment.py
import json
import os
import pytest
from datetime import datetime, date

@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    os.environ["COIN_DB_PATH"] = db_path

    # Seed sentiment data
    from sentiment.store import save_items, save_signal
    from sentiment.models import SentimentItem, SentimentSignal

    items = [
        SentimentItem("twitter", "BTC/USDT", 0.8, 0.9, "bullish tweet", datetime(2026, 4, 16, 12, 0)),
        SentimentItem("news", "BTC/USDT", 0.3, 0.7, "positive news", datetime(2026, 4, 16, 12, 5)),
        SentimentItem("twitter", "ETH/USDT", -0.5, 0.8, "bearish tweet", datetime(2026, 4, 16, 12, 10)),
    ]
    save_items(items, db_path=db_path)

    signals = [
        SentimentSignal("BTC/USDT", 0.65, "bullish", 0.85),
        SentimentSignal("ETH/USDT", -0.3, "bearish", 0.7),
    ]
    for sig in signals:
        save_signal(sig, db_path=db_path)

    from history_ui.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    yield app

    os.environ.pop("COIN_DB_PATH", None)

@pytest.fixture
def client(app):
    return app.test_client()


class TestSentimentLatest:
    def test_returns_signals(self, client):
        resp = client.get("/api/sentiment/latest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "signals" in data
        assert len(data["signals"]) >= 2

    def test_signal_fields(self, client):
        resp = client.get("/api/sentiment/latest")
        data = resp.get_json()
        sig = data["signals"][0]
        assert "symbol" in sig
        assert "score" in sig
        assert "direction" in sig
        assert "confidence" in sig


class TestSentimentItems:
    def test_returns_paginated(self, client):
        resp = client.get("/api/sentiment/items?page=1&per_page=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert "total" in data
        assert len(data["items"]) <= 10

    def test_filter_by_source(self, client):
        resp = client.get("/api/sentiment/items?source=twitter")
        data = resp.get_json()
        for item in data["items"]:
            assert item["source"] == "twitter"


class TestSentimentHistory:
    def test_returns_history(self, client):
        resp = client.get("/api/sentiment/history?symbol=BTC/USDT&days=7")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "history" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_sentiment.py -v`
Expected: FAIL — endpoints not implemented

- [ ] **Step 3: Check if create_app exists in history_ui/app.py**

Read `history_ui/app.py` to understand the Flask app factory pattern. If it uses a global `app` instead of `create_app()`, adjust the test fixture accordingly.

- [ ] **Step 4: Implement sentiment API endpoints in history_ui/api.py**

Add these endpoints to the existing `api_bp` Blueprint:

```python
@api_bp.route("/sentiment/latest")
def sentiment_latest():
    """各币种最新情绪信号。"""
    from sentiment.store import _get_conn
    conn = _get_conn()
    try:
        # Get distinct symbols with latest signal
        rows = conn.execute("""
            SELECT s1.* FROM sentiment_signals s1
            INNER JOIN (
                SELECT symbol, MAX(id) as max_id FROM sentiment_signals GROUP BY symbol
            ) s2 ON s1.id = s2.max_id
            ORDER BY s1.created_at DESC
        """).fetchall()
        signals = [dict(r) for r in rows]
        return jsonify({"signals": signals})
    finally:
        conn.close()


@api_bp.route("/sentiment/history")
def sentiment_history():
    """情绪分值时序数据。"""
    symbol = request.args.get("symbol", "")
    days = int(request.args.get("days", 7))
    from sentiment.store import _get_conn
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT date(created_at) as date, AVG(score) as score,
                   CASE WHEN AVG(score) > 0.1 THEN 'bullish'
                        WHEN AVG(score) < -0.1 THEN 'bearish'
                        ELSE 'neutral' END as direction
            FROM sentiment_signals
            WHERE (? = '' OR symbol = ?)
            AND created_at >= date('now', ? || ' days')
            GROUP BY date(created_at)
            ORDER BY date ASC
        """, (symbol, symbol, f"-{days}")).fetchall()
        return jsonify({"history": [dict(r) for r in rows]})
    finally:
        conn.close()


@api_bp.route("/sentiment/items")
def sentiment_items():
    """原始舆情条目，分页。"""
    source = request.args.get("source", "")
    symbol = request.args.get("symbol", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    offset = (page - 1) * per_page

    from sentiment.store import _get_conn
    conn = _get_conn()
    try:
        clauses = []
        params = []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM sentiment_items {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM sentiment_items {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        return jsonify({
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        })
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_sentiment.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add history_ui/api.py tests/test_api_sentiment.py
git commit -m "feat(api): add sentiment API endpoints (latest, history, items)"
```

---

## Task 2: Backend API — Portfolio Endpoints

**Files:**
- Modify: `history_ui/api.py`
- Test: `tests/test_api_portfolio.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api_portfolio.py
import json
import os
import pytest
from datetime import date

@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    os.environ["COIN_DB_PATH"] = db_path

    from portfolio.store import save_nav, save_weights, save_risk_event

    save_nav(date(2026, 4, 15), 10000.0, 10000.0, db_path=db_path)
    save_nav(date(2026, 4, 16), 10500.0, 10500.0, db_path=db_path)
    save_weights(date(2026, 4, 16), {"divergence": 0.4, "accumulation": 0.35, "breakout": 0.25}, db_path=db_path)
    save_risk_event("strategy", "divergence", "daily_limit", "loss exceeded 3%", db_path=db_path)

    from history_ui.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    yield app

    os.environ.pop("COIN_DB_PATH", None)

@pytest.fixture
def client(app):
    return app.test_client()


class TestPortfolioStatus:
    def test_returns_status(self, client):
        resp = client.get("/api/portfolio/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "weights" in data
        assert "nav" in data
        assert data["weights"]["divergence"] == 0.4

class TestPortfolioNavHistory:
    def test_returns_history(self, client):
        resp = client.get("/api/portfolio/nav-history?days=90")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "history" in data
        assert len(data["history"]) == 2

class TestPortfolioRiskEvents:
    def test_returns_events(self, client):
        resp = client.get("/api/portfolio/risk-events?limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data
        assert len(data["events"]) == 1
        assert data["events"][0]["level"] == "strategy"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_portfolio.py -v`

- [ ] **Step 3: Implement portfolio API endpoints**

Add to `history_ui/api.py`:

```python
@api_bp.route("/portfolio/status")
def portfolio_status():
    """当前组合状态。"""
    from portfolio.store import query_latest_weights, query_nav_history
    weights = query_latest_weights()
    nav_rows = query_nav_history(limit=1)

    nav = nav_rows[0]["nav"] if nav_rows else 0.0
    hwm = nav_rows[0]["high_water_mark"] if nav_rows else 0.0
    drawdown = (hwm - nav) / hwm if hwm > 0 else 0.0

    return jsonify({
        "weights": weights,
        "nav": nav,
        "high_water_mark": hwm,
        "drawdown_pct": round(drawdown, 4),
        "portfolio_halted": drawdown > 0.05,
        "halted_strategies": [],
    })


@api_bp.route("/portfolio/nav-history")
def portfolio_nav_history():
    """NAV 历史曲线。"""
    days = int(request.args.get("days", 90))
    from portfolio.store import query_nav_history
    history = query_nav_history(limit=days)
    history.reverse()  # oldest first for chart
    return jsonify({"history": history})


@api_bp.route("/portfolio/weights-history")
def portfolio_weights_history():
    """权重变化历史。"""
    from portfolio.store import _get_conn
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT date, strategy_id, weight FROM strategy_weights
            ORDER BY date ASC
        """).fetchall()
        # Group by date
        by_date = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = {"date": d, "weights": {}}
            by_date[d]["weights"][r["strategy_id"]] = r["weight"]
        return jsonify({"history": list(by_date.values())})
    finally:
        conn.close()


@api_bp.route("/portfolio/risk-events")
def portfolio_risk_events():
    """风控事件列表。"""
    limit = int(request.args.get("limit", 20))
    from portfolio.store import query_risk_events
    events = query_risk_events(limit=limit)
    return jsonify({"events": events})


@api_bp.route("/portfolio/rebalance", methods=["POST"])
def portfolio_rebalance():
    """触发再平衡。"""
    try:
        from main import load_config, run_portfolio_rebalance
        _, _, _, _, _, portfolio_config = load_config()
        run_portfolio_rebalance(portfolio_config)
        from portfolio.store import query_latest_weights
        weights = query_latest_weights()
        return jsonify({"success": True, "weights": weights})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_portfolio.py -v`

- [ ] **Step 5: Commit**

```bash
git add history_ui/api.py tests/test_api_portfolio.py
git commit -m "feat(api): add portfolio API endpoints (status, nav, weights, risk, rebalance)"
```

---

## Task 3: Frontend API Clients

**Files:**
- Create: `web/src/api/sentiment.ts`
- Create: `web/src/api/portfolio.ts`
- Modify: `web/src/api/client.ts` (add types)

- [ ] **Step 1: Create sentiment API client**

```typescript
// web/src/api/sentiment.ts
import { get } from "./client";

export interface SentimentSignalData {
  symbol: string;
  score: number;
  direction: string;
  confidence: number;
  created_at: string;
}

export interface SentimentItemData {
  id: number;
  source: string;
  symbol: string;
  score: number;
  confidence: number;
  raw_text: string;
  timestamp: string;
}

export interface SentimentHistoryPoint {
  date: string;
  score: number;
  direction: string;
}

export function fetchSentimentLatest() {
  return get<{ signals: SentimentSignalData[] }>("/sentiment/latest");
}

export function fetchSentimentHistory(symbol: string = "", days: number = 7) {
  return get<{ history: SentimentHistoryPoint[] }>("/sentiment/history", { symbol, days });
}

export function fetchSentimentItems(params: {
  source?: string;
  symbol?: string;
  page?: number;
  per_page?: number;
}) {
  return get<{ items: SentimentItemData[]; total: number; page: number; per_page: number }>(
    "/sentiment/items",
    params
  );
}
```

- [ ] **Step 2: Create portfolio API client**

```typescript
// web/src/api/portfolio.ts
import { get, post } from "./client";

export interface PortfolioStatus {
  weights: Record<string, number>;
  nav: number;
  high_water_mark: number;
  drawdown_pct: number;
  portfolio_halted: boolean;
  halted_strategies: string[];
}

export interface NavHistoryPoint {
  date: string;
  nav: number;
  high_water_mark: number;
}

export interface WeightsHistoryPoint {
  date: string;
  weights: Record<string, number>;
}

export interface RiskEvent {
  id: number;
  level: string;
  strategy_id: string;
  event_type: string;
  details: string;
  created_at: string;
}

export function fetchPortfolioStatus() {
  return get<PortfolioStatus>("/portfolio/status");
}

export function fetchNavHistory(days: number = 90) {
  return get<{ history: NavHistoryPoint[] }>("/portfolio/nav-history", { days });
}

export function fetchWeightsHistory(days: number = 90) {
  return get<{ history: WeightsHistoryPoint[] }>("/portfolio/weights-history", { days });
}

export function fetchRiskEvents(limit: number = 20) {
  return get<{ events: RiskEvent[] }>("/portfolio/risk-events", { limit });
}

export function triggerRebalance() {
  return post<{ success: boolean; weights?: Record<string, number>; error?: string }>(
    "/portfolio/rebalance"
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/api/sentiment.ts web/src/api/portfolio.ts
git commit -m "feat(web): add sentiment and portfolio API client functions"
```

---

## Task 4: Shared Components (StatCard, WeightsPieChart)

**Files:**
- Create: `web/src/components/StatCard.tsx`
- Create: `web/src/components/WeightsPieChart.tsx`

- [ ] **Step 1: Create StatCard component**

```tsx
// web/src/components/StatCard.tsx
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  color?: string;
}

export default function StatCard({ label, value, sub, icon: Icon, color = "text-blue-400" }: StatCardProps) {
  return (
    <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={16} className={color} />
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <div className="text-xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Create WeightsPieChart component**

```tsx
// web/src/components/WeightsPieChart.tsx
import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from "recharts";

const COLORS = ["#3b82f6", "#8b5cf6", "#f97316", "#10b981", "#ef4444", "#eab308"];

interface WeightsPieChartProps {
  weights: Record<string, number>;
}

export default function WeightsPieChart({ weights }: WeightsPieChartProps) {
  const data = Object.entries(weights).map(([name, value]) => ({
    name,
    value: Math.round(value * 1000) / 10,
  }));

  if (data.length === 0) {
    return <div className="text-sm text-slate-500 text-center py-8">暂无权重数据</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie data={data} cx="50%" cy="50%" innerRadius={50} outerRadius={90}
          dataKey="value" label={({ name, value }) => `${name} ${value}%`}
          labelLine={false}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(v: number) => `${v}%`} />
      </PieChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/StatCard.tsx web/src/components/WeightsPieChart.tsx
git commit -m "feat(web): add StatCard and WeightsPieChart components"
```

---

## Task 5: Sentiment Page Components + Page

**Files:**
- Create: `web/src/components/SentimentTable.tsx`
- Create: `web/src/components/SentimentChart.tsx`
- Create: `web/src/components/SentimentItems.tsx`
- Create: `web/src/pages/SentimentPage.tsx`

- [ ] **Step 1: Create SentimentTable**

```tsx
// web/src/components/SentimentTable.tsx
import type { SentimentSignalData } from "../api/sentiment";

interface Props {
  signals: SentimentSignalData[];
}

const dirColor: Record<string, string> = {
  bullish: "text-emerald-400",
  bearish: "text-red-400",
  neutral: "text-slate-400",
};

export default function SentimentTable({ signals }: Props) {
  if (signals.length === 0) {
    return <div className="text-sm text-slate-500 text-center py-8">暂无数据，请先运行舆情采集</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-500 border-b border-slate-800">
            <th className="text-left py-2 px-3">币种</th>
            <th className="text-right py-2 px-3">情绪分</th>
            <th className="text-center py-2 px-3">方向</th>
            <th className="text-right py-2 px-3">置信度</th>
            <th className="text-right py-2 px-3">更新时间</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s, i) => (
            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
              <td className="py-2 px-3 font-mono">{s.symbol || "全局"}</td>
              <td className="py-2 px-3 text-right font-mono">
                <span className={s.score > 0 ? "text-emerald-400" : s.score < 0 ? "text-red-400" : ""}>
                  {s.score > 0 ? "+" : ""}{s.score.toFixed(3)}
                </span>
              </td>
              <td className={`py-2 px-3 text-center ${dirColor[s.direction] || ""}`}>
                {s.direction}
              </td>
              <td className="py-2 px-3 text-right">{(s.confidence * 100).toFixed(0)}%</td>
              <td className="py-2 px-3 text-right text-slate-500">{s.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Create SentimentChart**

```tsx
// web/src/components/SentimentChart.tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import type { SentimentHistoryPoint } from "../api/sentiment";

interface Props {
  history: SentimentHistoryPoint[];
}

export default function SentimentChart({ history }: Props) {
  if (history.length === 0) {
    return <div className="text-sm text-slate-500 text-center py-8">暂无历史数据</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={history}>
        <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 12 }} />
        <YAxis domain={[-1, 1]} tick={{ fill: "#64748b", fontSize: 12 }} />
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
          labelStyle={{ color: "#94a3b8" }}
        />
        <ReferenceLine y={0} stroke="#334155" />
        <ReferenceLine y={0.1} stroke="#334155" strokeDasharray="3 3" />
        <ReferenceLine y={-0.1} stroke="#334155" strokeDasharray="3 3" />
        <Line type="monotone" dataKey="score" stroke="#3b82f6" strokeWidth={2}
          dot={{ fill: "#3b82f6", r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 3: Create SentimentItems**

```tsx
// web/src/components/SentimentItems.tsx
import { useState } from "react";
import type { SentimentItemData } from "../api/sentiment";

interface Props {
  items: SentimentItemData[];
  total: number;
  page: number;
  perPage: number;
  onPageChange: (page: number) => void;
  onSourceFilter: (source: string) => void;
  currentSource: string;
}

const SOURCES = ["", "twitter", "telegram", "news", "onchain"];

export default function SentimentItems({ items, total, page, perPage, onPageChange, onSourceFilter, currentSource }: Props) {
  const totalPages = Math.ceil(total / perPage);

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {SOURCES.map((s) => (
          <button key={s} onClick={() => onSourceFilter(s)}
            className={`px-3 py-1 rounded-lg text-xs ${currentSource === s ? "bg-blue-500/20 text-blue-400" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
            {s || "全部"}
          </button>
        ))}
      </div>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {items.map((item) => (
          <div key={item.id} className="bg-slate-800/50 rounded-lg p-3 text-sm">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{item.source}</span>
              <span className="text-xs text-slate-500">{item.timestamp}</span>
            </div>
            <div className="text-slate-300 line-clamp-2">{item.raw_text}</div>
            <div className="flex gap-4 mt-1 text-xs text-slate-500">
              <span>分值: <span className={item.score > 0 ? "text-emerald-400" : "text-red-400"}>{item.score.toFixed(2)}</span></span>
              {item.symbol && <span>币种: {item.symbol}</span>}
            </div>
          </div>
        ))}
      </div>
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          <button onClick={() => onPageChange(page - 1)} disabled={page <= 1}
            className="px-3 py-1 rounded bg-slate-800 text-slate-400 disabled:opacity-30">上一页</button>
          <span className="px-3 py-1 text-sm text-slate-500">{page} / {totalPages}</span>
          <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}
            className="px-3 py-1 rounded bg-slate-800 text-slate-400 disabled:opacity-30">下一页</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create SentimentPage**

```tsx
// web/src/pages/SentimentPage.tsx
import { useState, useEffect, useCallback } from "react";
import { Activity } from "lucide-react";
import { fetchSentimentLatest, fetchSentimentHistory, fetchSentimentItems } from "../api/sentiment";
import type { SentimentSignalData, SentimentHistoryPoint, SentimentItemData } from "../api/sentiment";
import SentimentTable from "../components/SentimentTable";
import SentimentChart from "../components/SentimentChart";
import SentimentItems from "../components/SentimentItems";

export default function SentimentPage() {
  const [signals, setSignals] = useState<SentimentSignalData[]>([]);
  const [history, setHistory] = useState<SentimentHistoryPoint[]>([]);
  const [items, setItems] = useState<SentimentItemData[]>([]);
  const [itemsTotal, setItemsTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchSentimentLatest().then((d) => setSignals(d.signals)).catch(() => setError("加载失败"));
    fetchSentimentHistory("", 7).then((d) => setHistory(d.history)).catch(() => {});
  }, []);

  const loadItems = useCallback(() => {
    fetchSentimentItems({ source, page, per_page: 20 })
      .then((d) => { setItems(d.items); setItemsTotal(d.total); })
      .catch(() => {});
  }, [source, page]);

  useEffect(() => { loadItems(); }, [loadItems]);

  const handleSourceFilter = (s: string) => { setSource(s); setPage(1); };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Activity size={20} className="text-blue-400" />
        <h1 className="text-lg font-semibold">舆情分析</h1>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-400 mb-3">情绪信号</h2>
        <SentimentTable signals={signals} />
      </div>

      <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-400 mb-3">情绪趋势（7天）</h2>
        <SentimentChart history={history} />
      </div>

      <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-400 mb-3">原始数据（{itemsTotal} 条）</h2>
        <SentimentItems items={items} total={itemsTotal} page={page} perPage={20}
          onPageChange={setPage} onSourceFilter={handleSourceFilter} currentSource={source} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/SentimentTable.tsx web/src/components/SentimentChart.tsx \
  web/src/components/SentimentItems.tsx web/src/pages/SentimentPage.tsx
git commit -m "feat(web): add sentiment page with table, chart, and items list"
```

---

## Task 6: Portfolio Page Components + Page

**Files:**
- Create: `web/src/components/NavChart.tsx`
- Create: `web/src/components/RiskStatus.tsx`
- Create: `web/src/pages/PortfolioPage.tsx`

- [ ] **Step 1: Create NavChart**

```tsx
// web/src/components/NavChart.tsx
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Line, ComposedChart } from "recharts";
import type { NavHistoryPoint } from "../api/portfolio";

interface Props {
  history: NavHistoryPoint[];
}

export default function NavChart({ history }: Props) {
  if (history.length === 0) {
    return <div className="text-sm text-slate-500 text-center py-8">暂无 NAV 数据</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={history}>
        <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 12 }} />
        <YAxis tick={{ fill: "#64748b", fontSize: 12 }} />
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
          labelStyle={{ color: "#94a3b8" }}
        />
        <Area type="monotone" dataKey="nav" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.1} strokeWidth={2} name="NAV" />
        <Line type="monotone" dataKey="high_water_mark" stroke="#f97316" strokeWidth={1}
          strokeDasharray="4 4" dot={false} name="高水位" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 2: Create RiskStatus**

```tsx
// web/src/components/RiskStatus.tsx
import { ShieldAlert, ShieldCheck } from "lucide-react";
import type { RiskEvent } from "../api/portfolio";

interface Props {
  halted: boolean;
  haltedStrategies: string[];
  drawdownPct: number;
  events: RiskEvent[];
}

const levelColor: Record<string, string> = {
  portfolio: "bg-red-500/20 text-red-400",
  strategy: "bg-yellow-500/20 text-yellow-400",
  position: "bg-blue-500/20 text-blue-400",
};

export default function RiskStatus({ halted, haltedStrategies, drawdownPct, events }: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {halted ? (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/15 text-red-400">
            <ShieldAlert size={18} />
            <span className="text-sm font-semibold">组合已暂停开仓</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/15 text-emerald-400">
            <ShieldCheck size={18} />
            <span className="text-sm font-semibold">风控正常</span>
          </div>
        )}
        <span className="text-sm text-slate-500">回撤: {(drawdownPct * 100).toFixed(2)}%</span>
      </div>

      {haltedStrategies.length > 0 && (
        <div className="text-sm text-yellow-400">
          暂停策略: {haltedStrategies.join(", ")}
        </div>
      )}

      {events.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          <h3 className="text-xs text-slate-500 font-semibold">风控事件</h3>
          {events.map((e) => (
            <div key={e.id} className="flex items-start gap-2 text-sm">
              <span className={`px-2 py-0.5 rounded text-xs ${levelColor[e.level] || "bg-slate-700"}`}>
                {e.level}
              </span>
              <div className="flex-1">
                <span className="text-slate-300">{e.strategy_id}: {e.event_type}</span>
                <span className="text-slate-500 text-xs ml-2">{e.created_at}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create PortfolioPage**

```tsx
// web/src/pages/PortfolioPage.tsx
import { useState, useEffect } from "react";
import { Briefcase, RefreshCw, DollarSign, TrendingUp } from "lucide-react";
import { fetchPortfolioStatus, fetchNavHistory, fetchRiskEvents, triggerRebalance } from "../api/portfolio";
import type { PortfolioStatus, NavHistoryPoint, RiskEvent } from "../api/portfolio";
import StatCard from "../components/StatCard";
import WeightsPieChart from "../components/WeightsPieChart";
import NavChart from "../components/NavChart";
import RiskStatus from "../components/RiskStatus";

export default function PortfolioPage() {
  const [status, setStatus] = useState<PortfolioStatus | null>(null);
  const [navHistory, setNavHistory] = useState<NavHistoryPoint[]>([]);
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [rebalancing, setRebalancing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchPortfolioStatus().then(setStatus).catch(() => setError("加载失败"));
    fetchNavHistory(90).then((d) => setNavHistory(d.history)).catch(() => {});
    fetchRiskEvents(20).then((d) => setEvents(d.events)).catch(() => {});
  }, []);

  const handleRebalance = async () => {
    setRebalancing(true);
    try {
      const result = await triggerRebalance();
      if (result.success && result.weights) {
        setStatus((prev) => prev ? { ...prev, weights: result.weights! } : prev);
      }
    } catch {
      setError("再平衡失败");
    } finally {
      setRebalancing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Briefcase size={20} className="text-purple-400" />
          <h1 className="text-lg font-semibold">组合管理</h1>
        </div>
        <button onClick={handleRebalance} disabled={rebalancing}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 disabled:opacity-50 text-sm">
          <RefreshCw size={14} className={rebalancing ? "animate-spin" : ""} />
          {rebalancing ? "再平衡中..." : "再平衡"}
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {status && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard label="净值" value={status.nav.toFixed(2)} icon={DollarSign} color="text-blue-400" />
          <StatCard label="高水位" value={status.high_water_mark.toFixed(2)} icon={TrendingUp} color="text-emerald-400" />
          <StatCard label="回撤" value={`${(status.drawdown_pct * 100).toFixed(2)}%`}
            icon={TrendingUp} color={status.drawdown_pct > 0.03 ? "text-red-400" : "text-slate-400"} />
          <StatCard label="策略数" value={String(Object.keys(status.weights).length)} icon={Briefcase} color="text-purple-400" />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 mb-3">策略权重</h2>
          {status && <WeightsPieChart weights={status.weights} />}
          {status && (
            <table className="w-full text-sm mt-2">
              <tbody>
                {Object.entries(status.weights).map(([sid, w]) => (
                  <tr key={sid} className="border-b border-slate-800/50">
                    <td className="py-1 px-2">{sid}</td>
                    <td className="py-1 px-2 text-right font-mono">{(w * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 mb-3">风控状态</h2>
          {status && (
            <RiskStatus halted={status.portfolio_halted} haltedStrategies={status.halted_strategies}
              drawdownPct={status.drawdown_pct} events={events} />
          )}
        </div>
      </div>

      <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-400 mb-3">NAV 曲线</h2>
        <NavChart history={navHistory} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/src/components/NavChart.tsx web/src/components/RiskStatus.tsx web/src/pages/PortfolioPage.tsx
git commit -m "feat(web): add portfolio page with NAV chart, weights pie, risk status"
```

---

## Task 7: Dashboard Page (综合首页)

**Files:**
- Create: `web/src/pages/DashboardV2.tsx`

- [ ] **Step 1: Create DashboardV2**

```tsx
// web/src/pages/DashboardV2.tsx
import { useState, useEffect } from "react";
import { LayoutDashboard, DollarSign, Activity, TrendingUp, ShieldAlert } from "lucide-react";
import { fetchDashboard, fetchActiveSignals } from "../api/client";
import { fetchSentimentLatest } from "../api/sentiment";
import { fetchPortfolioStatus, fetchRiskEvents } from "../api/portfolio";
import type { SentimentSignalData } from "../api/sentiment";
import type { PortfolioStatus, RiskEvent } from "../api/portfolio";
import StatCard from "../components/StatCard";
import WeightsPieChart from "../components/WeightsPieChart";

export default function DashboardV2() {
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [sentiment, setSentiment] = useState<SentimentSignalData[]>([]);
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [dashboard, setDashboard] = useState<any>(null);

  useEffect(() => {
    fetchPortfolioStatus().then(setPortfolio).catch(() => {});
    fetchSentimentLatest().then((d) => setSentiment(d.signals)).catch(() => {});
    fetchRiskEvents(5).then((d) => setEvents(d.events)).catch(() => {});
    fetchDashboard().then(setDashboard).catch(() => {});
  }, []);

  // Find global sentiment or first available
  const globalSentiment = sentiment.find((s) => s.symbol === "") || sentiment[0];
  const sentimentLabel = globalSentiment
    ? globalSentiment.direction === "bullish" ? "贪婪" : globalSentiment.direction === "bearish" ? "恐慌" : "中性"
    : "--";
  const sentimentColor = globalSentiment
    ? globalSentiment.direction === "bullish" ? "text-emerald-400" : globalSentiment.direction === "bearish" ? "text-red-400" : "text-slate-400"
    : "text-slate-400";

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <LayoutDashboard size={20} className="text-blue-400" />
        <h1 className="text-lg font-semibold">Dashboard</h1>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="总净值" value={portfolio ? portfolio.nav.toFixed(2) : "--"} icon={DollarSign} color="text-blue-400" />
        <StatCard label="回撤" value={portfolio ? `${(portfolio.drawdown_pct * 100).toFixed(2)}%` : "--"}
          icon={TrendingUp} color={portfolio && portfolio.drawdown_pct > 0.03 ? "text-red-400" : "text-emerald-400"} />
        <StatCard label="市场情绪" value={sentimentLabel}
          sub={globalSentiment ? `${globalSentiment.score > 0 ? "+" : ""}${globalSentiment.score.toFixed(3)}` : undefined}
          icon={Activity} color={sentimentColor} />
        <StatCard label="策略数" value={portfolio ? String(Object.keys(portfolio.weights).length) : "--"} icon={ShieldAlert}
          color="text-purple-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 mb-3">策略权重</h2>
          {portfolio ? <WeightsPieChart weights={portfolio.weights} /> : <div className="text-sm text-slate-500 text-center py-8">暂无数据</div>}
        </div>

        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 mb-3">最近风控事件</h2>
          {events.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8">无风控事件</div>
          ) : (
            <div className="space-y-2">
              {events.map((e) => (
                <div key={e.id} className="flex items-center gap-2 text-sm">
                  <span className={`px-2 py-0.5 rounded text-xs ${e.level === "portfolio" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"}`}>
                    {e.level}
                  </span>
                  <span className="text-slate-300 flex-1">{e.strategy_id}: {e.event_type}</span>
                  <span className="text-xs text-slate-500">{e.created_at}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {dashboard?.top_signals && dashboard.top_signals.length > 0 && (
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-400 mb-3">最近扫描信号</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2 px-3">币种</th>
                  <th className="text-right py-2 px-3">价格</th>
                  <th className="text-right py-2 px-3">评分</th>
                  <th className="text-center py-2 px-3">模式</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.top_signals.slice(0, 10).map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 px-3 font-mono">{s.symbol}</td>
                    <td className="py-2 px-3 text-right">{s.price?.toFixed(4)}</td>
                    <td className="py-2 px-3 text-right font-mono text-blue-400">{s.score?.toFixed(3)}</td>
                    <td className="py-2 px-3 text-center text-xs">{s.mode}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/pages/DashboardV2.tsx
git commit -m "feat(web): add comprehensive Dashboard page with sentiment + portfolio overview"
```

---

## Task 8: Router + Navigation Update

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/Layout.tsx`

- [ ] **Step 1: Update App.tsx routes**

Add the new route imports and route entries. Read the existing `App.tsx` first. Add:

```tsx
import SentimentPage from "./pages/SentimentPage";
import PortfolioPage from "./pages/PortfolioPage";
import DashboardV2 from "./pages/DashboardV2";
```

Replace the `index` route's Dashboard with DashboardV2:
```tsx
<Route index element={<DashboardV2 />} />
```

Add new routes inside the Layout Route:
```tsx
<Route path="sentiment" element={<SentimentPage />} />
<Route path="portfolio" element={<PortfolioPage />} />
```

- [ ] **Step 2: Update Layout.tsx navigation**

Read the existing `Layout.tsx` to understand the nav pattern. Add two new NavLink items for 舆情 and 组合, using `Activity` and `Briefcase` icons from lucide-react. Place them after the existing nav items.

Desktop sidebar addition:
```tsx
<NavLink to="/sentiment" ...>
  <Activity size={18} /> 舆情
</NavLink>
<NavLink to="/portfolio" ...>
  <Briefcase size={18} /> 组合
</NavLink>
```

Mobile bottom nav: add the same two items.

- [ ] **Step 3: Build and verify**

```bash
cd web && npm run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/App.tsx web/src/components/Layout.tsx
git commit -m "feat(web): add sentiment and portfolio routes and navigation"
```

---

## Task 9: Playwright E2E Tests — Setup + Dashboard

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_dashboard.py`

- [ ] **Step 1: Install playwright**

```bash
.venv/bin/pip install pytest-playwright
.venv/bin/playwright install chromium
echo 'pytest-playwright>=0.5.0' >> requirements.txt
```

- [ ] **Step 2: Create conftest.py with fixtures**

```python
# tests/e2e/conftest.py
import os
import subprocess
import time
import socket
import pytest
from datetime import datetime, date

def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("e2e") / "test.db")
    os.environ["COIN_DB_PATH"] = path
    return path


@pytest.fixture(scope="session")
def seed_db(db_path):
    """Seed test data for all E2E tests."""
    from sentiment.models import SentimentItem, SentimentSignal
    from sentiment.store import save_items, save_signal
    from portfolio.store import save_nav, save_weights, save_risk_event

    items = [
        SentimentItem("twitter", "BTC/USDT", 0.8, 0.9, "BTC moon!", datetime(2026, 4, 16, 12, 0)),
        SentimentItem("news", "BTC/USDT", 0.3, 0.7, "BTC news", datetime(2026, 4, 16, 12, 5)),
        SentimentItem("onchain", "ETH/USDT", -0.5, 0.9, '{"direction":"inflow"}', datetime(2026, 4, 16, 12, 10)),
        SentimentItem("telegram", "SOL/USDT", 0.6, 0.5, "SOL pump", datetime(2026, 4, 16, 12, 15)),
    ]
    save_items(items, db_path=db_path)

    for sig in [
        SentimentSignal("BTC/USDT", 0.65, "bullish", 0.85),
        SentimentSignal("ETH/USDT", -0.3, "bearish", 0.7),
        SentimentSignal("", 0.2, "bullish", 0.6),
    ]:
        save_signal(sig, db_path=db_path)

    for i in range(30):
        d = date(2026, 3, 17 + i)
        nav = 10000 + i * 50
        save_nav(d, nav, max(10000, nav), db_path=db_path)

    save_weights(date(2026, 4, 16), {"divergence": 0.4, "accumulation": 0.35, "breakout": 0.25}, db_path=db_path)
    save_risk_event("strategy", "divergence", "daily_limit", "loss exceeded 3%", db_path=db_path)


@pytest.fixture(scope="session")
def server_url(seed_db, db_path):
    """Start Flask server on a random port."""
    port = _find_free_port()
    env = os.environ.copy()
    env["COIN_DB_PATH"] = db_path
    env["HISTORY_UI_PORT"] = str(port)
    env["HISTORY_UI_HOST"] = "127.0.0.1"

    proc = subprocess.Popen(
        [".venv/bin/python", "-m", "history_ui"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"{url}/api/config", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Flask server failed to start")

    yield url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def app_page(page, server_url):
    """Navigate to the app and return page."""
    page.goto(f"{server_url}/app/")
    page.wait_for_load_state("networkidle")
    return page
```

- [ ] **Step 3: Create Dashboard E2E tests**

```python
# tests/e2e/test_dashboard.py
import pytest
from playwright.sync_api import expect


class TestDashboardSmoke:
    def test_page_loads(self, app_page):
        expect(app_page.locator("h1")).to_contain_text("Dashboard")

    def test_no_console_errors(self, app_page):
        errors = []
        app_page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        app_page.reload()
        app_page.wait_for_load_state("networkidle")
        assert len(errors) == 0, f"Console errors: {errors}"

    def test_stat_cards_present(self, app_page):
        cards = app_page.locator('[class*="rounded-xl"]')
        expect(cards.first).to_be_visible()


class TestDashboardFunctional:
    def test_nav_value_displayed(self, app_page):
        # NAV card should show a number, not "--"
        app_page.wait_for_timeout(1000)
        nav_text = app_page.locator("text=总净值").locator("..").locator("div.text-xl").text_content()
        assert nav_text != "--"

    def test_sentiment_indicator_present(self, app_page):
        app_page.wait_for_timeout(1000)
        sentiment = app_page.locator("text=市场情绪").locator("..").locator("div.text-xl")
        text = sentiment.text_content()
        assert text in ("贪婪", "恐慌", "中性", "--")
```

- [ ] **Step 4: Run E2E tests**

```bash
.venv/bin/pytest tests/e2e/test_dashboard.py -v --headed
```

Expected: All pass (or adjust selectors based on actual rendering)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/ requirements.txt
git commit -m "test(e2e): add Playwright setup and Dashboard E2E tests"
```

---

## Task 10: Playwright E2E — Sentiment + Portfolio Tests

**Files:**
- Create: `tests/e2e/test_sentiment.py`
- Create: `tests/e2e/test_portfolio.py`

- [ ] **Step 1: Create Sentiment E2E tests**

```python
# tests/e2e/test_sentiment.py
import pytest
from playwright.sync_api import expect


class TestSentimentSmoke:
    def test_page_loads(self, page, server_url):
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        expect(page.locator("h1")).to_contain_text("舆情分析")

    def test_sections_present(self, page, server_url):
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        expect(page.locator("text=情绪信号")).to_be_visible()
        expect(page.locator("text=情绪趋势")).to_be_visible()
        expect(page.locator("text=原始数据")).to_be_visible()

    def test_no_console_errors(self, page, server_url):
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        assert len(errors) == 0


class TestSentimentFunctional:
    def test_signal_table_has_rows(self, page, server_url):
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        rows = page.locator("table tbody tr")
        expect(rows.first).to_be_visible()

    def test_source_filter(self, page, server_url):
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        # Click twitter filter
        page.locator("button", has_text="twitter").click()
        page.wait_for_timeout(500)
        # Verify items section updates
        expect(page.locator("text=原始数据")).to_be_visible()

    def test_chart_renders(self, page, server_url):
        page.goto(f"{server_url}/app/sentiment")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        # Recharts renders SVG
        chart_container = page.locator(".recharts-responsive-container").first
        # Chart may or may not have data, but container should exist
        expect(chart_container).to_be_visible()
```

- [ ] **Step 2: Create Portfolio E2E tests**

```python
# tests/e2e/test_portfolio.py
import pytest
from playwright.sync_api import expect


class TestPortfolioSmoke:
    def test_page_loads(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        expect(page.locator("h1")).to_contain_text("组合管理")

    def test_sections_present(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        expect(page.locator("text=策略权重")).to_be_visible()
        expect(page.locator("text=风控状态")).to_be_visible()
        expect(page.locator("text=NAV 曲线")).to_be_visible()

    def test_no_console_errors(self, page, server_url):
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        assert len(errors) == 0


class TestPortfolioFunctional:
    def test_nav_value_shown(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        expect(page.locator("text=净值").first).to_be_visible()

    def test_weights_table_visible(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        # Weight table should have strategy names
        expect(page.locator("text=divergence").first).to_be_visible()

    def test_risk_status_visible(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        # Should show either "风控正常" or "组合已暂停开仓"
        risk_text = page.locator("text=风控正常").or_(page.locator("text=组合已暂停开仓"))
        expect(risk_text.first).to_be_visible()

    def test_rebalance_button_exists(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        btn = page.locator("button", has_text="再平衡")
        expect(btn).to_be_visible()

    def test_nav_chart_renders(self, page, server_url):
        page.goto(f"{server_url}/app/portfolio")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        chart = page.locator(".recharts-responsive-container").first
        expect(chart).to_be_visible()
```

- [ ] **Step 3: Run all E2E tests**

```bash
.venv/bin/pytest tests/e2e/ -v --headed
```

Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_sentiment.py tests/e2e/test_portfolio.py
git commit -m "test(e2e): add Playwright E2E tests for sentiment and portfolio pages"
```
