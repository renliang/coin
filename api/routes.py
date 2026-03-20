from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select
from db.models import Order, AccountSnapshot, get_session
from datetime import datetime
import asyncio
import json

app = FastAPI(title="Coin Quant Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局引用（由 main.py 注入）
_execution_engine = None
_strategies = []
_ws_clients: list[WebSocket] = []
_db_path: str = "coin.db"


def set_engine(engine):
    global _execution_engine
    _execution_engine = engine


def set_strategies(strategies):
    global _strategies
    _strategies = strategies


def set_db_path(path: str):
    global _db_path
    _db_path = path


@app.get("/api/positions")
def get_positions():
    if _execution_engine is None:
        return []
    return [
        {
            "strategy_id": sid,
            "symbol": o.symbol,
            "direction": o.direction,
            "size": o.size,
            "entry_price": o.entry_price,
            "stop_loss": o.stop_loss,
        }
        for sid, o in _execution_engine._positions.items()
    ]


@app.get("/api/orders")
def get_orders():
    with get_session(_db_path) as session:
        orders = session.exec(select(Order).order_by(Order.opened_at.desc()).limit(100)).all()
    return [o.model_dump() for o in orders]


@app.get("/api/account")
async def get_account():
    if _execution_engine is None:
        return {"balance": 0, "available": 0, "daily_pnl": 0}
    try:
        balance_info = await _execution_engine.exchange.fetch_balance()
        usdt = balance_info.get("USDT", {})
        current_balance = usdt.get("total", 0)

        # 今日盈亏：当前余额 - 今日最早快照余额
        daily_pnl = 0.0
        try:
            with get_session(_db_path) as session:
                today = datetime.utcnow().date()
                today_start = datetime.combine(today, datetime.min.time())
                snapshots = session.exec(
                    select(AccountSnapshot)
                    .where(AccountSnapshot.snapshot_at >= today_start)
                    .order_by(AccountSnapshot.snapshot_at)
                ).all()
                if snapshots:
                    daily_pnl = current_balance - snapshots[0].balance
        except Exception:
            pass

        return {
            "balance": current_balance,
            "available": usdt.get("free", 0),
            "daily_pnl": daily_pnl,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/strategies")
def get_strategies():
    return [
        {
            "id": s.strategy_id,
            "symbol": s.symbol,
            "timeframe": s.timeframe,
            "enabled": s.enabled,
        }
        for s in _strategies
    ]


@app.post("/api/strategy/{strategy_id}/stop")
def stop_strategy(strategy_id: str):
    for s in _strategies:
        if s.strategy_id == strategy_id:
            s.enabled = False
            return {"status": "stopped"}
    return {"error": "strategy not found"}


@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            positions = get_positions()
            await websocket.send_text(json.dumps({"type": "positions", "data": positions}))
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
