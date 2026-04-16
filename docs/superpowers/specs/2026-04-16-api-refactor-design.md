# 前后端分离重构：Flask → FastAPI + React 独立运行

> 日期：2026-04-16
> 状态：设计阶段

## 1. 目标

将 Flask（history_ui/）替换为 FastAPI 纯 API 服务，React SPA 独立运行，实现前后端完全分离。删除冗余的 Jinja2 模板。

## 2. 现状

```
history_ui/
├── app.py          # Flask app + Jinja2 模板路由 + 静态文件服务
├── api.py          # Blueprint: 21 个 API 端点
├── templates/      # Jinja2 模板（冗余）
├── static/         # CSS（冗余）
└── __main__.py     # 入口

web/                # React SPA（消费 /api/* 端点，由 Flask 服务静态文件）
```

## 3. 目标架构

```
api/                     # 【新建】FastAPI 纯 API 服务
├── __init__.py
├── __main__.py          # uvicorn 入口
├── app.py               # FastAPI app + CORS + router 挂载
├── routes/
│   ├── __init__.py
│   ├── scanner.py       # 迁移：dashboard/signals/positions/coin/performance/scan/klines/config
│   ├── sentiment.py     # 迁移：sentiment/latest, history, items
│   └── portfolio.py     # 迁移：portfolio/status, nav-history, weights-history, risk-events, rebalance
└── deps.py              # 共享依赖

web/                     # 【修改】独立前端
├── vite.config.ts       # 新增 dev proxy: /api → localhost:8000
├── src/api/client.ts    # 不变（相对路径 /api）
└── ...

history_ui/              # 【删除】
```

## 4. FastAPI 应用

### api/app.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title="Coin Quant API", docs_url="/docs")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    from api.routes.scanner import router as scanner_router
    from api.routes.sentiment import router as sentiment_router
    from api.routes.portfolio import router as portfolio_router

    app.include_router(scanner_router, prefix="/api")
    app.include_router(sentiment_router, prefix="/api")
    app.include_router(portfolio_router, prefix="/api")

    return app
```

### api/__main__.py

```python
import uvicorn
from api.app import create_app
app = create_app()
uvicorn.run(app, host="0.0.0.0", port=8000)
```

## 5. 路由迁移

所有端点保持相同的 URL 路径和响应格式。

### scanner.py (13 端点)

| Flask | FastAPI |
|-------|---------|
| `@api_bp.route("/dashboard")` | `@router.get("/dashboard")` |
| `@api_bp.route("/signals")` | `@router.get("/signals")` |
| `@api_bp.route("/positions")` | `@router.get("/positions")` |
| `@api_bp.route("/positions/closed")` | `@router.get("/positions/closed")` |
| `@api_bp.route("/coin/<symbol>")` | `@router.get("/coin/{symbol}")` |
| `@api_bp.route("/performance")` | `@router.get("/performance")` |
| `@api_bp.route("/scan", methods=["POST"])` | `@router.post("/scan")` |
| `@api_bp.route("/scan/status")` | `@router.get("/scan/status")` |
| `@api_bp.route("/klines/<symbol>")` | `@router.get("/klines/{symbol}")` |
| `@api_bp.route("/signals/active")` | `@router.get("/signals/active")` |
| `@api_bp.route("/signals/outcomes")` | `@router.get("/signals/outcomes")` |
| `@api_bp.route("/signals/trend")` | `@router.get("/signals/trend")` |
| `@api_bp.route("/config")` | `@router.get("/config")` |

### sentiment.py (3 端点)

| Flask | FastAPI |
|-------|---------|
| `@api_bp.route("/sentiment/latest")` | `@router.get("/sentiment/latest")` |
| `@api_bp.route("/sentiment/history")` | `@router.get("/sentiment/history")` |
| `@api_bp.route("/sentiment/items")` | `@router.get("/sentiment/items")` |

### portfolio.py (5 端点)

| Flask | FastAPI |
|-------|---------|
| `@api_bp.route("/portfolio/status")` | `@router.get("/portfolio/status")` |
| `@api_bp.route("/portfolio/nav-history")` | `@router.get("/portfolio/nav-history")` |
| `@api_bp.route("/portfolio/weights-history")` | `@router.get("/portfolio/weights-history")` |
| `@api_bp.route("/portfolio/risk-events")` | `@router.get("/portfolio/risk-events")` |
| `@api_bp.route("/portfolio/rebalance", methods=["POST"])` | `@router.post("/portfolio/rebalance")` |

## 6. Flask → FastAPI 转换规则

| Flask | FastAPI |
|-------|---------|
| `request.args.get("key", default)` | `key: str = Query(default)` 参数注入 |
| `request.args.get("key", 1, type=int)` | `key: int = Query(1)` |
| `jsonify({...})` | 直接 `return {...}` |
| `@api_bp.route("/path/<var>")` | `@router.get("/path/{var}")` |
| `abort(404)` | `raise HTTPException(status_code=404)` |
| Blueprint | APIRouter |
| Flask test_client | httpx.AsyncClient (TestClient) |

## 7. 前端修改

### vite.config.ts

```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
```

### client.ts

不需要修改 — 已使用相对路径 `/api`。

## 8. CLI 和 serve 模式更新

### main.py run_serve

将 Flask 启动替换为 uvicorn 启动：

```python
import uvicorn
from api.app import create_app
app = create_app()
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### ecosystem.config.js

更新 PM2 配置使用 uvicorn。

## 9. 测试迁移

### API 测试

- `tests/test_api_sentiment.py` — Flask test_client → FastAPI TestClient (httpx)
- `tests/test_api_portfolio.py` — 同上
- 所有现有测试逻辑不变，只改客户端初始化方式

### E2E 测试

- `tests/e2e/conftest.py` — 启动命令从 `python -m history_ui` 改为 `python -m api`
- 测试内容不变

## 10. 依赖变化

新增：
```
fastapi>=0.115.0
uvicorn>=0.30.0
httpx>=0.27.0    # FastAPI TestClient 依赖
```

删除（从 requirements.txt 移除）：
```
flask>=3.0.0
flask-cors>=4.0.0
```

注意：如果 `history_ui/` 的 Flask 代码在其他地方被 import，需要确认无残留引用。

## 11. 删除文件

```
history_ui/           # 整个目录删除
├── __init__.py
├── __main__.py
├── app.py
├── api.py
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── history.html
│   └── coin.html
└── static/
    └── style.css
```

## 12. 不变的部分

- `scanner/`, `sentiment/`, `portfolio/` 模块完全不动
- `main.py`, `cli/`, `config.yaml` 核心逻辑不动
- React 组件和页面不动
- 所有 API 响应格式不变（前端零改动）
- SQLite 数据和 scanner.db 不动
