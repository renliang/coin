# 币圈个人量化交易系统 — 设计文档

**日期：** 2026-03-20
**状态：** 已批准

---

## 概述

个人用途的加密货币量化交易系统，专注于 OKX 合约市场。采用混合方案：底层 I/O 使用成熟开源库（`ccxt` / `ccxt.pro`），上层策略引擎、风控、执行层完全自建，配合 Web Dashboard 进行监控和管理。

---

## 目标

- 支持 OKX 合约（U 本位永续合约）实盘交易
- 支持动量策略、突破策略，可扩展自定义策略
- K 线级别回测，策略代码与实盘共用
- Web Dashboard 实时监控账户、持仓、策略状态
- 风控前置，保护账户安全

---

## 技术选型

| 层级 | 技术 |
|------|------|
| 交易所接入 | `ccxt` + `ccxt.pro`（异步 WebSocket） |
| 技术指标 | `pandas-ta` |
| 后端 API | FastAPI |
| 数据库 | SQLite（通过 SQLModel ORM） |
| 前端 | React + TailwindCSS + Recharts |
| 任务调度 | `asyncio` 事件循环 |
| 配置管理 | `config.yaml` + `pydantic` 解析 |

---

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                   Web Dashboard                  │
│              (React + FastAPI)                   │
└───────────────────┬─────────────────────────────┘
                    │ REST / WebSocket
┌───────────────────▼─────────────────────────────┐
│                  Core Engine                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │   Data   │  │ Strategy │  │   Execution   │  │
│  │  Layer   │→ │  Engine  │→ │    Engine     │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│                     ↑               ↓            │
│              ┌──────────┐  ┌───────────────┐    │
│              │   Risk   │  │    OKX API    │    │
│              │ Manager  │  │   (ccxt)      │    │
│              └──────────┘  └───────────────┘    │
└─────────────────────────────────────────────────┘
         ↓ 历史数据
┌─────────────────┐
│  Backtest Engine│
└─────────────────┘
```

**数据流：**
1. Data Layer 拉取 OKX K 线 + WebSocket 实时行情
2. Strategy Engine 消费行情，产出交易信号
3. Risk Manager 审核信号
4. Execution Engine 向 OKX 下单，维护持仓状态
5. 所有状态写入 SQLite，Web Dashboard 读取展示

---

## 模块设计

### 1. Data Layer

**职责：** 获取和缓存所有行情数据。

**两条数据通道：**
- REST API：历史 K 线拉取（启动补全 + 定时同步），支持 1m / 5m / 15m / 1h / 4h / 1d
- WebSocket：实时 K 线推送（当前 bar 更新）+ 实时成交价

**K 线管理：**
- 每个 `(symbol, timeframe)` 维护滚动窗口（最近 500 根）
- 新 bar 收盘时触发策略计算
- 用 `pandas DataFrame` 存内存

**容错：**
- WebSocket 断线自动重连（指数退避）
- REST 请求限速（遵守 OKX rate limit）
- 数据缺口自动补全

---

### 2. Strategy Engine

**职责：** 定义策略接口，驱动信号生成。

**基类接口：**

```python
class BaseStrategy:
    def on_bar(self, symbol: str, timeframe: str, df: DataFrame) -> Signal | None:
        """每根 K 线收盘时调用，返回信号或 None"""

    def on_tick(self, symbol: str, price: float):
        """实时价格更新（用于动态止损）"""
```

**信号结构：**

```python
@dataclass
class Signal:
    symbol: str
    direction: Literal["long", "short", "close"]
    entry_price: float
    stop_loss: float
    take_profit: float | None
    reason: str
```

**内置策略模板：**
- 动量策略：EMA 趋势过滤 + RSI 超卖/超买入场
- 突破策略：N 周期最高/最低价突破 + ATR 止损

**多策略支持：**
- 每个策略独立运行，互不干扰
- 同一 symbol 可运行多个不同周期策略
- 策略信号独立发送给 Risk Manager

---

### 3. Risk Manager

**职责：** 信号审核 + 仓位定额计算。

**审核流程：**
1. 日亏损检查：当前亏损是否超过 `daily_loss_limit`
2. 并发仓位检查：当前持仓数是否超过 `max_open_positions`
3. 仓位定额计算：`size = (账户余额 × risk_per_trade%) ÷ (入场价 - 止损价)`
4. 杠杆检查：计算所需杠杆是否超过 `max_leverage`

**核心配置参数：**
- `max_risk_per_trade`: 单笔最大风险（默认 1%）
- `max_open_positions`: 最大同时持仓数（默认 3）
- `daily_loss_limit`: 日亏损上限（默认 5%）
- `max_leverage`: 最大杠杆倍数（默认 5x）

---

### 4. Execution Engine

**职责：** 订单生命周期管理。

**开仓流程：**
- 市价单入场
- 同时挂 OKX 附带止盈止损单（TPSL），止损在交易所侧执行

**持仓状态机：**
```
PENDING → OPEN → CLOSING → CLOSED
```

**关键细节：**
- 使用 OKX TPSL 功能，止损单不依赖本地进程存活
- 启动时从 OKX 拉取当前持仓，恢复内部状态
- 所有订单写入 SQLite

---

### 5. Backtest Engine

**职责：** K 线级别历史回测，与实盘共用策略代码。

**运行流程：**
1. 加载历史 K 线（OKX REST 拉取或本地 CSV）
2. 逐根 K 线 replay，调用 `strategy.on_bar()`
3. 模拟 Risk Manager 审核（相同参数）
4. 模拟成交（下一根 open 价）
5. 模拟资金费率（每 8 小时按历史费率扣除）
6. 输出绩效报告

**输出指标：**
- 总收益率、年化收益率
- 最大回撤（MDD）
- Sharpe Ratio
- 胜率、盈亏比
- 逐笔交易明细

---

### 6. Web Dashboard

**后端 API（FastAPI）：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/positions` | 当前持仓 |
| GET | `/api/orders` | 历史订单 |
| GET | `/api/account` | 账户余额 + 今日盈亏 |
| GET | `/api/strategies` | 策略运行状态 |
| POST | `/api/strategy/{id}/stop` | 手动停止策略 |
| WS | `/ws/feed` | 实时推送行情 + 持仓变化 |

**前端页面布局：**
```
┌─────────────────────────────────────┐
│  账户总览：余额 / 今日盈亏 / 持仓数   │
├──────────────┬──────────────────────┤
│  当前持仓列表  │   K线图 + 信号标记   │
├──────────────┴──────────────────────┤
│         策略运行状态 + 开关           │
├─────────────────────────────────────┤
│         历史订单 + 收益曲线           │
└─────────────────────────────────────┘
```

---

## 项目目录结构

```
coin/
├── core/
│   ├── data/          # DataLayer, WebSocket 管理
│   ├── strategy/      # BaseStrategy, Signal, 内置策略模板
│   ├── risk/          # RiskManager
│   ├── execution/     # ExecutionEngine, 订单状态机
│   └── backtest/      # BacktestEngine
├── strategies/        # 用户自定义策略
├── api/               # FastAPI 路由
├── web/               # React 前端
├── db/                # SQLite models (SQLModel)
├── config.yaml        # 所有参数配置
└── main.py            # 启动入口
```

---

## 数据库 Schema（SQLite）

**orders 表：**
- `id`, `symbol`, `direction`, `size`, `entry_price`, `exit_price`
- `stop_loss`, `take_profit`, `status`, `strategy_id`
- `opened_at`, `closed_at`, `pnl`

**account_snapshots 表：**
- `id`, `balance`, `unrealized_pnl`, `daily_pnl`, `snapshot_at`

---

## 配置文件示例

```yaml
exchange:
  id: okx
  api_key: ""
  secret: ""
  password: ""  # OKX 需要 passphrase
  sandbox: false

risk:
  max_risk_per_trade: 0.01   # 1%
  max_open_positions: 3
  daily_loss_limit: 0.05     # 5%
  max_leverage: 5

strategies:
  - name: momentum_btc
    class: MomentumStrategy
    symbol: BTC-USDT-SWAP
    timeframe: 1h
    params:
      ema_period: 20
      rsi_period: 14

web:
  host: 0.0.0.0
  port: 8080
```

---

## 依赖清单

```
ccxt>=4.0
ccxt[pro]
pandas
pandas-ta
fastapi
uvicorn
sqlmodel
pydantic
pyyaml
websockets
```
