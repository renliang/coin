# 币圈个人量化交易系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建基于 OKX 合约的个人量化交易系统，支持动量/突破策略、K 线回测、Web Dashboard 监控。

**Architecture:** Python 异步核心引擎（asyncio）+ FastAPI 后端 + React 前端。底层交易所接入用 `ccxt`/`ccxt.pro`，策略/风控/执行层完全自建，SQLite 持久化状态。

**Tech Stack:** Python 3.11+, ccxt, ccxt[pro], pandas, pandas-ta, FastAPI, SQLModel, SQLite, React, TailwindCSS, Recharts

---

## 文件结构

```
coin/
├── core/
│   ├── __init__.py
│   ├── config.py              # 配置加载（pydantic）
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py         # REST K线拉取
│   │   └── stream.py          # WebSocket 实时行情
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseStrategy, Signal
│   │   └── templates/
│   │       ├── momentum.py    # 动量策略模板
│   │       └── breakout.py    # 突破策略模板
│   ├── risk/
│   │   ├── __init__.py
│   │   └── manager.py         # RiskManager
│   ├── execution/
│   │   ├── __init__.py
│   │   └── engine.py          # ExecutionEngine, 订单状态机
│   └── backtest/
│       ├── __init__.py
│       └── engine.py          # BacktestEngine
├── strategies/                # 用户自定义策略
│   └── __init__.py
├── api/
│   ├── __init__.py
│   └── routes.py              # FastAPI 路由
├── db/
│   ├── __init__.py
│   └── models.py              # SQLModel 数据模型
├── web/                       # React 前端（单独构建）
├── tests/
│   ├── test_config.py
│   ├── test_fetcher.py
│   ├── test_strategy.py
│   ├── test_risk.py
│   ├── test_execution.py
│   └── test_backtest.py
├── config.yaml                # 配置文件
├── main.py                    # 启动入口
└── requirements.txt
```

---

## Task 1: 项目基础 + 配置系统

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `core/__init__.py`
- Create: `core/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 创建 requirements.txt**

```
ccxt>=4.0.0
ccxt[pro]
pandas>=2.0.0
pandas-ta>=0.3.14b
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
sqlmodel>=0.0.16
pydantic>=2.0.0
pydantic-settings
pyyaml>=6.0
websockets>=12.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: 创建 config.yaml**

```yaml
exchange:
  id: okx
  api_key: ""
  secret: ""
  password: ""
  sandbox: true  # 先用沙盒环境

risk:
  max_risk_per_trade: 0.01
  max_open_positions: 3
  daily_loss_limit: 0.05
  max_leverage: 5

strategies: []

web:
  host: 0.0.0.0
  port: 8080

database:
  path: coin.db
```

- [ ] **Step 3: 写 core/config.py**

```python
from pathlib import Path
from pydantic import BaseModel
import yaml


class ExchangeConfig(BaseModel):
    id: str = "okx"
    api_key: str = ""
    secret: str = ""
    password: str = ""
    sandbox: bool = True


class RiskConfig(BaseModel):
    max_risk_per_trade: float = 0.01
    max_open_positions: int = 3
    daily_loss_limit: float = 0.05
    max_leverage: float = 5.0


class StrategyConfig(BaseModel):
    name: str
    class_name: str
    symbol: str
    timeframe: str
    params: dict = {}


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class DatabaseConfig(BaseModel):
    path: str = "coin.db"


class AppConfig(BaseModel):
    exchange: ExchangeConfig = ExchangeConfig()
    risk: RiskConfig = RiskConfig()
    strategies: list[StrategyConfig] = []
    web: WebConfig = WebConfig()
    database: DatabaseConfig = DatabaseConfig()


def load_config(path: str = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)
```

- [ ] **Step 4: 写 tests/test_config.py**

```python
from core.config import load_config, AppConfig


def test_load_default_config(tmp_path):
    config = load_config("nonexistent.yaml")
    assert isinstance(config, AppConfig)
    assert config.risk.max_risk_per_trade == 0.01


def test_load_config_from_file(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("risk:\n  max_risk_per_trade: 0.02\n")
    config = load_config(str(cfg_file))
    assert config.risk.max_risk_per_trade == 0.02
```

- [ ] **Step 5: 安装依赖并运行测试**

```bash
pip install -r requirements.txt
pytest tests/test_config.py -v
```

期望：2 tests PASSED

- [ ] **Step 6: Commit**

```bash
git init
git add .
git commit -m "feat: project scaffold + config system"
```

---

## Task 2: 数据库模型

**Files:**
- Create: `db/__init__.py`
- Create: `db/models.py`

- [ ] **Step 1: 写 db/models.py**

```python
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    direction: str          # long / short
    size: float
    entry_price: float
    exit_price: Optional[float] = None
    stop_loss: float
    take_profit: Optional[float] = None
    status: str = "PENDING"  # PENDING / OPEN / CLOSING / CLOSED
    strategy_id: str
    okx_order_id: Optional[str] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    pnl: Optional[float] = None


class AccountSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    balance: float
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)


def get_engine(db_path: str = "coin.db"):
    return create_engine(f"sqlite:///{db_path}")


def create_tables(db_path: str = "coin.db"):
    engine = get_engine(db_path)
    SQLModel.metadata.create_all(engine)


def get_session(db_path: str = "coin.db"):
    engine = get_engine(db_path)
    return Session(engine)
```

- [ ] **Step 2: 写测试验证表结构**

在 `tests/test_config.py` 末尾追加（或创建 `tests/test_db.py`）：

```python
# tests/test_db.py
from db.models import create_tables, get_session, Order
from datetime import datetime


def test_create_and_query_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    create_tables(db_path)
    with get_session(db_path) as session:
        order = Order(
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=0.01,
            entry_price=50000.0,
            stop_loss=49000.0,
            strategy_id="test_strategy",
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        assert order.id is not None
        assert order.status == "PENDING"
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_db.py -v
```

期望：1 test PASSED

- [ ] **Step 4: Commit**

```bash
git add db/ tests/test_db.py
git commit -m "feat: database models (Order, AccountSnapshot)"
```

---

## Task 3: Data Layer — REST K 线拉取

**Files:**
- Create: `core/data/__init__.py`
- Create: `core/data/fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: 写 core/data/fetcher.py**

```python
import asyncio
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd


class KlineFetcher:
    """从交易所拉取历史 K 线"""

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "", password: str = "", sandbox: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange: ccxt.Exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        拉取 K 线数据，返回 DataFrame。
        列: timestamp, open, high, low, close, volume
        """
        raw = await self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    async def close(self):
        await self.exchange.close()
```

- [ ] **Step 2: 写 tests/test_fetcher.py（使用 mock，不真实请求）**

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from core.data.fetcher import KlineFetcher


@pytest.fixture
def mock_exchange():
    with patch("core.data.fetcher.ccxt") as mock_ccxt:
        exchange_instance = AsyncMock()
        exchange_class = MagicMock(return_value=exchange_instance)
        mock_ccxt.okx = exchange_class
        exchange_instance.fetch_ohlcv.return_value = [
            [1700000000000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0],
            [1700003600000, 50500.0, 52000.0, 50000.0, 51500.0, 120.0],
        ]
        yield exchange_instance


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_dataframe(mock_exchange):
    fetcher = KlineFetcher("okx")
    fetcher.exchange = mock_exchange
    df = await fetcher.fetch_ohlcv("BTC-USDT-SWAP", "1h", limit=2)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[0] == 50500.0
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_fetcher.py -v
```

期望：1 test PASSED

- [ ] **Step 4: Commit**

```bash
git add core/data/ tests/test_fetcher.py
git commit -m "feat: kline fetcher with ccxt async"
```

---

## Task 4: Data Layer — WebSocket 实时行情

**Files:**
- Create: `core/data/stream.py`

- [ ] **Step 1: 写 core/data/stream.py**

```python
import asyncio
import logging
from typing import Callable, Awaitable
import ccxt.pro as ccxtpro
import pandas as pd

logger = logging.getLogger(__name__)

BarCallback = Callable[[str, str, pd.DataFrame], Awaitable[None]]


class MarketStream:
    """WebSocket 实时行情流，断线自动重连"""

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "", password: str = "", sandbox: bool = True):
        exchange_class = getattr(ccxtpro, exchange_id)
        self.exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)
        self._callbacks: list[BarCallback] = []
        self._running = False

    def on_bar(self, callback: BarCallback):
        """注册 K 线收盘回调"""
        self._callbacks.append(callback)

    async def watch_candles(self, symbol: str, timeframe: str):
        """持续监听 K 线更新，新 bar 收盘时触发回调"""
        self._running = True
        backoff = 1
        while self._running:
            try:
                candles = await self.exchange.watch_ohlcv(symbol, timeframe)
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                for cb in self._callbacks:
                    await cb(symbol, timeframe, df)
                backoff = 1
            except Exception as e:
                logger.warning(f"WebSocket error: {e}, retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def stop(self):
        self._running = False
        await self.exchange.close()
```

- [ ] **Step 2: Commit（此模块 mock 测试复杂，集成测试阶段覆盖）**

```bash
git add core/data/stream.py
git commit -m "feat: websocket market stream with auto-reconnect"
```

---

## Task 5: Strategy Engine — BaseStrategy + Signal

**Files:**
- Create: `core/strategy/__init__.py`
- Create: `core/strategy/base.py`
- Create: `tests/test_strategy.py`

- [ ] **Step 1: 写 core/strategy/base.py**

```python
from dataclasses import dataclass, field
from typing import Literal, Optional
import pandas as pd


@dataclass
class Signal:
    symbol: str
    direction: Literal["long", "short", "close"]
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    reason: str = ""
    strategy_id: str = ""


class BaseStrategy:
    """所有策略的基类"""

    def __init__(self, strategy_id: str, symbol: str, timeframe: str, params: dict = {}):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.params = params
        self.enabled = True

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        每根 K 线收盘时调用。
        df: 包含最近 N 根 K 线的 DataFrame，列为 open/high/low/close/volume
        返回 Signal 或 None
        """
        raise NotImplementedError

    def on_tick(self, symbol: str, price: float):
        """实时价格更新（可选覆写，用于动态止损）"""
        pass

    def should_handle(self, symbol: str, timeframe: str) -> bool:
        return symbol == self.symbol and timeframe == self.timeframe
```

- [ ] **Step 2: 写 tests/test_strategy.py**

```python
import pandas as pd
import pytest
from core.strategy.base import BaseStrategy, Signal


class AlwaysBuyStrategy(BaseStrategy):
    def on_bar(self, symbol, timeframe, df):
        price = df["close"].iloc[-1]
        return Signal(
            symbol=symbol,
            direction="long",
            entry_price=price,
            stop_loss=price * 0.99,
            strategy_id=self.strategy_id,
        )


def make_df(n=20):
    return pd.DataFrame({
        "open": [100.0] * n,
        "high": [105.0] * n,
        "low": [95.0] * n,
        "close": [102.0] * n,
        "volume": [1000.0] * n,
    })


def test_signal_returned():
    s = AlwaysBuyStrategy("test", "BTC-USDT-SWAP", "1h")
    sig = s.on_bar("BTC-USDT-SWAP", "1h", make_df())
    assert sig is not None
    assert sig.direction == "long"
    assert sig.stop_loss < sig.entry_price


def test_should_handle():
    s = AlwaysBuyStrategy("test", "BTC-USDT-SWAP", "1h")
    assert s.should_handle("BTC-USDT-SWAP", "1h")
    assert not s.should_handle("ETH-USDT-SWAP", "1h")


def test_no_signal_returns_none():
    class NeverBuy(BaseStrategy):
        def on_bar(self, symbol, timeframe, df):
            return None

    s = NeverBuy("test", "BTC-USDT-SWAP", "1h")
    assert s.on_bar("BTC-USDT-SWAP", "1h", make_df()) is None
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_strategy.py -v
```

期望：3 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add core/strategy/ tests/test_strategy.py
git commit -m "feat: BaseStrategy + Signal dataclass"
```

---

## Task 6: 内置策略模板

**Files:**
- Create: `core/strategy/templates/__init__.py`
- Create: `core/strategy/templates/momentum.py`
- Create: `core/strategy/templates/breakout.py`

- [ ] **Step 1: 写动量策略 core/strategy/templates/momentum.py**

```python
from typing import Optional
import pandas as pd
import pandas_ta as ta
from core.strategy.base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    """
    EMA 趋势过滤 + RSI 超卖/超买入场
    params:
      ema_period: int = 20
      rsi_period: int = 14
      rsi_oversold: float = 30
      rsi_overbought: float = 70
      atr_period: int = 14
      atr_sl_multiplier: float = 1.5
    """

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        if not self.should_handle(symbol, timeframe) or not self.enabled:
            return None
        if len(df) < max(self.params.get("ema_period", 20), self.params.get("rsi_period", 14)) + 5:
            return None

        ema_period = self.params.get("ema_period", 20)
        rsi_period = self.params.get("rsi_period", 14)
        rsi_oversold = self.params.get("rsi_oversold", 30)
        rsi_overbought = self.params.get("rsi_overbought", 70)
        atr_period = self.params.get("atr_period", 14)
        atr_sl_mult = self.params.get("atr_sl_multiplier", 1.5)

        ema = ta.ema(df["close"], length=ema_period)
        rsi = ta.rsi(df["close"], length=rsi_period)
        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)

        if ema is None or rsi is None or atr is None:
            return None

        price = df["close"].iloc[-1]
        ema_val = ema.iloc[-1]
        rsi_val = rsi.iloc[-1]
        atr_val = atr.iloc[-1]

        # 多单：价格在 EMA 上方 + RSI 超卖反弹
        if price > ema_val and rsi_val < rsi_oversold:
            sl = price - atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="long",
                entry_price=price,
                stop_loss=sl,
                reason=f"EMA上方+RSI超卖({rsi_val:.1f})",
                strategy_id=self.strategy_id,
            )

        # 空单：价格在 EMA 下方 + RSI 超买
        if price < ema_val and rsi_val > rsi_overbought:
            sl = price + atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="short",
                entry_price=price,
                stop_loss=sl,
                reason=f"EMA下方+RSI超买({rsi_val:.1f})",
                strategy_id=self.strategy_id,
            )

        return None
```

- [ ] **Step 2: 写突破策略 core/strategy/templates/breakout.py**

```python
from typing import Optional
import pandas as pd
import pandas_ta as ta
from core.strategy.base import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    """
    N 周期最高/最低价突破 + ATR 止损
    params:
      lookback: int = 20       # 突破周期
      atr_period: int = 14
      atr_sl_multiplier: float = 2.0
    """

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        if not self.should_handle(symbol, timeframe) or not self.enabled:
            return None

        lookback = self.params.get("lookback", 20)
        atr_period = self.params.get("atr_period", 14)
        atr_sl_mult = self.params.get("atr_sl_multiplier", 2.0)

        if len(df) < lookback + atr_period + 5:
            return None

        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
        if atr is None:
            return None

        price = df["close"].iloc[-1]
        prev_high = df["high"].iloc[-lookback - 1:-1].max()
        prev_low = df["low"].iloc[-lookback - 1:-1].min()
        atr_val = atr.iloc[-1]

        if price > prev_high:
            sl = price - atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="long",
                entry_price=price,
                stop_loss=sl,
                reason=f"突破{lookback}周期高点({prev_high:.2f})",
                strategy_id=self.strategy_id,
            )

        if price < prev_low:
            sl = price + atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="short",
                entry_price=price,
                stop_loss=sl,
                reason=f"跌破{lookback}周期低点({prev_low:.2f})",
                strategy_id=self.strategy_id,
            )

        return None
```

- [ ] **Step 3: 写模板策略测试（追加到 tests/test_strategy.py）**

```python
# 追加到 tests/test_strategy.py

import numpy as np
from core.strategy.templates.momentum import MomentumStrategy
from core.strategy.templates.breakout import BreakoutStrategy


def make_trend_df(n=100, trend="up"):
    prices = np.linspace(100, 120, n) if trend == "up" else np.linspace(120, 100, n)
    prices += np.random.normal(0, 0.5, n)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": [1000.0] * n,
    })


def test_momentum_returns_signal_or_none():
    s = MomentumStrategy("m1", "BTC-USDT-SWAP", "1h")
    df = make_trend_df(100)
    result = s.on_bar("BTC-USDT-SWAP", "1h", df)
    # 可能有信号也可能没有，重要的是不崩溃
    assert result is None or result.direction in ("long", "short")


def test_breakout_requires_enough_bars():
    s = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 20})
    short_df = make_trend_df(10)  # 数据不足
    result = s.on_bar("BTC-USDT-SWAP", "1h", short_df)
    assert result is None


def test_breakout_long_signal_on_new_high():
    s = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 5})
    prices = [100.0] * 30
    prices[-1] = 115.0  # 新高突破
    df = pd.DataFrame({
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [1000.0] * 30,
    })
    result = s.on_bar("BTC-USDT-SWAP", "1h", df)
    assert result is not None
    assert result.direction == "long"
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_strategy.py -v
```

期望：6 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add core/strategy/templates/ tests/test_strategy.py
git commit -m "feat: momentum and breakout strategy templates"
```

---

## Task 7: Risk Manager

**Files:**
- Create: `core/risk/__init__.py`
- Create: `core/risk/manager.py`
- Create: `tests/test_risk.py`

- [ ] **Step 1: 写 core/risk/manager.py**

```python
import logging
from dataclasses import dataclass
from typing import Optional
from core.strategy.base import Signal
from core.config import RiskConfig

logger = logging.getLogger(__name__)


@dataclass
class ApprovedSignal:
    signal: Signal
    size: float          # 计算后的合约张数
    leverage: float      # 建议杠杆


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self._daily_pnl: float = 0.0
        self._open_positions: int = 0
        self._account_balance: float = 0.0

    def update_account(self, balance: float, daily_pnl: float, open_positions: int):
        self._account_balance = balance
        self._daily_pnl = daily_pnl
        self._open_positions = open_positions

    def evaluate(self, signal: Signal) -> Optional[ApprovedSignal]:
        """审核信号，通过则返回 ApprovedSignal，否则返回 None"""
        if self._account_balance <= 0:
            logger.warning("账户余额为 0，拒绝信号")
            return None

        # 1. 日亏损检查
        daily_loss_ratio = abs(min(self._daily_pnl, 0)) / self._account_balance
        if daily_loss_ratio >= self.config.daily_loss_limit:
            logger.warning(f"日亏损 {daily_loss_ratio:.2%} 超过上限，拒绝信号")
            return None

        # 2. 并发仓位检查（平仓信号不受限制）
        if signal.direction != "close" and self._open_positions >= self.config.max_open_positions:
            logger.warning(f"持仓数 {self._open_positions} 已达上限，拒绝信号")
            return None

        # 3. 仓位定额计算
        risk_amount = self._account_balance * self.config.max_risk_per_trade
        price_risk = abs(signal.entry_price - signal.stop_loss)
        if price_risk <= 0:
            logger.warning("止损价与入场价相同，拒绝信号")
            return None

        # size = 风险金额 / 单张风险（USDT 本位合约，1张=1U名义价值/合约乘数，这里简化为张数）
        size = risk_amount / price_risk

        # 4. 杠杆检查（简化：名义价值 / 余额）
        notional = size * signal.entry_price
        leverage = notional / self._account_balance
        if leverage > self.config.max_leverage:
            # 缩小 size 到杠杆上限
            size = (self._account_balance * self.config.max_leverage) / signal.entry_price
            leverage = self.config.max_leverage

        return ApprovedSignal(signal=signal, size=round(size, 4), leverage=round(leverage, 2))
```

- [ ] **Step 2: 写 tests/test_risk.py**

```python
import pytest
from core.risk.manager import RiskManager
from core.strategy.base import Signal
from core.config import RiskConfig


def make_risk_manager(balance=10000.0):
    cfg = RiskConfig(max_risk_per_trade=0.01, max_open_positions=3, daily_loss_limit=0.05, max_leverage=5.0)
    rm = RiskManager(cfg)
    rm.update_account(balance=balance, daily_pnl=0.0, open_positions=0)
    return rm


def make_signal(direction="long", entry=50000.0, sl=49000.0):
    return Signal(symbol="BTC-USDT-SWAP", direction=direction, entry_price=entry, stop_loss=sl, strategy_id="test")


def test_normal_signal_approved():
    rm = make_risk_manager()
    result = rm.evaluate(make_signal())
    assert result is not None
    assert result.size > 0


def test_size_calculation():
    rm = make_risk_manager(balance=10000.0)
    # risk = 10000 * 0.01 = 100 USDT
    # price_risk = 50000 - 49000 = 1000
    # size = 100 / 1000 = 0.1
    result = rm.evaluate(make_signal(entry=50000.0, sl=49000.0))
    assert result is not None
    assert abs(result.size - 0.1) < 0.001


def test_daily_loss_limit_blocks_signal():
    rm = make_risk_manager(balance=10000.0)
    rm.update_account(balance=10000.0, daily_pnl=-600.0, open_positions=0)  # -6% 超过 5% 上限
    result = rm.evaluate(make_signal())
    assert result is None


def test_max_positions_blocks_signal():
    rm = make_risk_manager()
    rm.update_account(balance=10000.0, daily_pnl=0.0, open_positions=3)
    result = rm.evaluate(make_signal())
    assert result is None


def test_zero_balance_blocks_signal():
    rm = make_risk_manager(balance=0.0)
    result = rm.evaluate(make_signal())
    assert result is None


def test_leverage_cap_reduces_size():
    rm = make_risk_manager(balance=1000.0)  # 小余额，容易超杠杆
    result = rm.evaluate(make_signal(entry=50000.0, sl=49990.0))  # 很小的止损距离
    assert result is not None
    assert result.leverage <= 5.0
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_risk.py -v
```

期望：6 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add core/risk/ tests/test_risk.py
git commit -m "feat: risk manager with position sizing"
```

---

## Task 8: Execution Engine

**Files:**
- Create: `core/execution/__init__.py`
- Create: `core/execution/engine.py`
- Create: `tests/test_execution.py`

- [ ] **Step 1: 写 core/execution/engine.py**

```python
import asyncio
import logging
from typing import Optional
import ccxt.async_support as ccxt
from core.risk.manager import ApprovedSignal
from core.config import ExchangeConfig
from db.models import Order, get_session, create_tables

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, exchange_config: ExchangeConfig, db_path: str = "coin.db"):
        exchange_class = getattr(ccxt, exchange_config.id)
        self.exchange = exchange_class({
            "apiKey": exchange_config.api_key,
            "secret": exchange_config.secret,
            "password": exchange_config.password,
            "enableRateLimit": True,
        })
        if exchange_config.sandbox:
            self.exchange.set_sandbox_mode(True)
        self.db_path = db_path
        create_tables(db_path)
        self._positions: dict[str, Order] = {}  # strategy_id -> Order

    async def execute(self, approved: ApprovedSignal) -> Optional[Order]:
        """执行已审核的信号"""
        sig = approved.signal

        if sig.direction == "close":
            return await self._close_position(sig.symbol, sig.strategy_id)

        return await self._open_position(approved)

    async def _open_position(self, approved: ApprovedSignal) -> Optional[Order]:
        sig = approved.signal
        side = "buy" if sig.direction == "long" else "sell"

        try:
            # 设置杠杆
            await self.exchange.set_leverage(int(approved.leverage), sig.symbol)

            # 市价开仓，附带止损单
            params = {
                "stopLoss": {"triggerPrice": sig.stop_loss, "type": "market"},
            }
            if sig.take_profit:
                params["takeProfit"] = {"triggerPrice": sig.take_profit, "type": "market"}

            result = await self.exchange.create_order(
                symbol=sig.symbol,
                type="market",
                side=side,
                amount=approved.size,
                params=params,
            )

            order = Order(
                symbol=sig.symbol,
                direction=sig.direction,
                size=approved.size,
                entry_price=result.get("average", sig.entry_price),
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                status="OPEN",
                strategy_id=sig.strategy_id,
                okx_order_id=result.get("id"),
            )

            with get_session(self.db_path) as session:
                session.add(order)
                session.commit()
                session.refresh(order)

            self._positions[sig.strategy_id] = order
            logger.info(f"开仓成功: {sig.symbol} {sig.direction} {approved.size} @ {order.entry_price}")
            return order

        except Exception as e:
            logger.error(f"开仓失败: {e}")
            return None

    async def _close_position(self, symbol: str, strategy_id: str) -> Optional[Order]:
        order = self._positions.get(strategy_id)
        if not order:
            logger.warning(f"找不到策略 {strategy_id} 的持仓")
            return None

        close_side = "sell" if order.direction == "long" else "buy"
        try:
            await self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=close_side,
                amount=order.size,
                params={"reduceOnly": True},
            )
            order.status = "CLOSED"
            with get_session(self.db_path) as session:
                session.add(order)
                session.commit()
            del self._positions[strategy_id]
            logger.info(f"平仓成功: {symbol} {strategy_id}")
            return order
        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return None

    async def sync_positions(self):
        """启动时从交易所同步当前持仓"""
        try:
            positions = await self.exchange.fetch_positions()
            for pos in positions:
                if pos["contracts"] and pos["contracts"] > 0:
                    logger.info(f"已同步持仓: {pos['symbol']} {pos['side']} {pos['contracts']}")
        except Exception as e:
            logger.warning(f"同步持仓失败: {e}")

    async def close(self):
        await self.exchange.close()
```

- [ ] **Step 2: 写 tests/test_execution.py**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.execution.engine import ExecutionEngine
from core.risk.manager import ApprovedSignal
from core.strategy.base import Signal
from core.config import ExchangeConfig


def make_approved_signal():
    sig = Signal(
        symbol="BTC-USDT-SWAP",
        direction="long",
        entry_price=50000.0,
        stop_loss=49000.0,
        strategy_id="test_strategy",
    )
    return ApprovedSignal(signal=sig, size=0.1, leverage=2.0)


@pytest.fixture
def engine(tmp_path):
    cfg = ExchangeConfig(id="okx", sandbox=True)
    eng = ExecutionEngine(cfg, db_path=str(tmp_path / "test.db"))
    eng.exchange = AsyncMock()
    eng.exchange.create_order.return_value = {
        "id": "order123",
        "average": 50000.0,
    }
    eng.exchange.set_leverage = AsyncMock()
    return eng


@pytest.mark.asyncio
async def test_open_position_creates_order(engine):
    approved = make_approved_signal()
    order = await engine.execute(approved)
    assert order is not None
    assert order.status == "OPEN"
    assert order.okx_order_id == "order123"


@pytest.mark.asyncio
async def test_close_position_requires_open_position(engine):
    from core.strategy.base import Signal
    close_sig = Signal(
        symbol="BTC-USDT-SWAP",
        direction="close",
        entry_price=51000.0,
        stop_loss=0.0,
        strategy_id="nonexistent",
    )
    approved = ApprovedSignal(signal=close_sig, size=0.1, leverage=1.0)
    result = await engine.execute(approved)
    assert result is None  # 没有持仓，返回 None
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_execution.py -v
```

期望：2 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add core/execution/ tests/test_execution.py
git commit -m "feat: execution engine with OKX TPSL order support"
```

---

## Task 9: Backtest Engine

**Files:**
- Create: `core/backtest/__init__.py`
- Create: `core/backtest/engine.py`
- Create: `tests/test_backtest.py`

- [ ] **Step 1: 写 core/backtest/engine.py**

```python
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from core.strategy.base import BaseStrategy, Signal
from core.config import RiskConfig
from core.risk.manager import RiskManager


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    entry_idx: int
    exit_idx: int


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    initial_balance: float = 10000.0
    final_balance: float = 10000.0

    @property
    def total_return(self) -> float:
        return (self.final_balance - self.initial_balance) / self.initial_balance

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        balance = self.initial_balance
        peak = balance
        max_dd = 0.0
        for t in self.trades:
            balance += t.pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl for t in self.trades if t.pnl > 0)
        losses = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return gains / losses if losses > 0 else float("inf")

    @property
    def annualized_return(self) -> float:
        if not self.trades:
            return 0.0
        n_trades = len(self.trades)
        # 假设每笔平均持仓 1 小时，粗略年化
        hours = n_trades  # 简化估算
        years = hours / 8760
        if years <= 0:
            return 0.0
        return (1 + self.total_return) ** (1 / years) - 1

    @property
    def sharpe_ratio(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        import numpy as np
        pnls = [t.pnl for t in self.trades]
        mean = np.mean(pnls)
        std = np.std(pnls)
        if std == 0:
            return 0.0
        return mean / std * (252 ** 0.5)  # 年化 Sharpe（假设每日频率）


class BacktestEngine:
    def __init__(self, strategy: BaseStrategy, risk_config: RiskConfig, initial_balance: float = 10000.0):
        self.strategy = strategy
        self.risk = RiskManager(risk_config)
        self.initial_balance = initial_balance

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        逐根 K 线回测。
        df: 完整历史 K 线，index 为 timestamp
        """
        result = BacktestResult(initial_balance=self.initial_balance)
        balance = self.initial_balance
        open_trade: Optional[dict] = None
        daily_pnl = 0.0

        for i in range(50, len(df)):  # 前50根用于指标预热
            window = df.iloc[:i + 1]
            current_price = df["close"].iloc[i]

            # 检查止损/止盈
            if open_trade:
                hit_sl = hit_tp = False
                if open_trade["direction"] == "long":
                    hit_sl = current_price <= open_trade["stop_loss"]
                    hit_tp = open_trade["take_profit"] and current_price >= open_trade["take_profit"]
                else:
                    hit_sl = current_price >= open_trade["stop_loss"]
                    hit_tp = open_trade["take_profit"] and current_price <= open_trade["take_profit"]

                if hit_sl or hit_tp:
                    exit_price = open_trade["stop_loss"] if hit_sl else open_trade["take_profit"]
                    direction = open_trade["direction"]
                    size = open_trade["size"]
                    pnl = (exit_price - open_trade["entry_price"]) * size * (1 if direction == "long" else -1)
                    balance += pnl
                    daily_pnl += pnl
                    result.trades.append(Trade(
                        symbol=self.strategy.symbol,
                        direction=direction,
                        entry_price=open_trade["entry_price"],
                        exit_price=exit_price,
                        size=size,
                        pnl=pnl,
                        entry_idx=open_trade["entry_idx"],
                        exit_idx=i,
                    ))
                    open_trade = None

            # 更新风控状态
            open_count = 1 if open_trade else 0
            self.risk.update_account(balance=balance, daily_pnl=daily_pnl, open_positions=open_count)

            # 已有持仓时不开新仓（简化）
            if open_trade:
                continue

            # 调用策略
            signal: Optional[Signal] = self.strategy.on_bar(self.strategy.symbol, self.strategy.timeframe, window)
            if signal is None or signal.direction == "close":
                continue

            approved = self.risk.evaluate(signal)
            if approved is None:
                continue

            open_trade = {
                "direction": signal.direction,
                "entry_price": df["close"].iloc[i + 1] if i + 1 < len(df) else current_price,  # 下根 open 成交
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "size": approved.size,
                "entry_idx": i,
            }

        result.final_balance = balance
        return result
```

- [ ] **Step 2: 写 tests/test_backtest.py**

```python
import numpy as np
import pandas as pd
import pytest
from core.backtest.engine import BacktestEngine, BacktestResult
from core.strategy.templates.breakout import BreakoutStrategy
from core.config import RiskConfig


def make_sinusoidal_df(n=300):
    """生成带趋势的正弦波价格数据"""
    t = np.linspace(0, 6 * np.pi, n)
    prices = 100 + 20 * np.sin(t) + t * 0.5
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": [1000.0] * n,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))


def test_backtest_runs_without_error():
    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 10})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(make_sinusoidal_df())
    assert isinstance(result, BacktestResult)


def test_backtest_result_properties():
    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 10})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(make_sinusoidal_df(300))
    assert 0.0 <= result.win_rate <= 1.0
    assert result.max_drawdown >= 0.0
    assert isinstance(result.total_return, float)


def test_backtest_with_no_signals():
    """数据太少时不应崩溃"""
    from core.strategy.templates.momentum import MomentumStrategy
    strategy = MomentumStrategy("m1", "BTC-USDT-SWAP", "1h")
    risk = RiskConfig()
    engine = BacktestEngine(strategy, risk)
    short_df = make_sinusoidal_df(10)
    result = engine.run(short_df)
    assert len(result.trades) == 0
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_backtest.py -v
```

期望：3 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add core/backtest/ tests/test_backtest.py
git commit -m "feat: backtest engine with trade simulation"
```

---

## Task 10: FastAPI 后端

**Files:**
- Create: `api/__init__.py`
- Create: `api/routes.py`

- [ ] **Step 1: 写 api/routes.py**

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select
from db.models import Order, AccountSnapshot, get_session
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


def set_engine(engine):
    global _execution_engine
    _execution_engine = engine


def set_strategies(strategies):
    global _strategies
    _strategies = strategies


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
def get_orders(db_path: str = "coin.db"):
    with get_session(db_path) as session:
        orders = session.exec(select(Order).order_by(Order.opened_at.desc()).limit(100)).all()
    return [o.model_dump() for o in orders]


@app.get("/api/account")
async def get_account():
    if _execution_engine is None:
        return {"balance": 0, "daily_pnl": 0}
    try:
        balance_info = await _execution_engine.exchange.fetch_balance()
        usdt = balance_info.get("USDT", {})
        # 今日盈亏：从数据库最早一条今日账户快照计算
        from datetime import date
        from sqlmodel import select
        today_start = daily_pnl = 0.0
        try:
            with get_session() as session:
                from datetime import datetime
                today = datetime.utcnow().date()
                snapshots = session.exec(
                    select(AccountSnapshot)
                    .where(AccountSnapshot.snapshot_at >= datetime.combine(today, datetime.min.time()))
                    .order_by(AccountSnapshot.snapshot_at)
                ).all()
                if snapshots:
                    daily_pnl = usdt.get("total", 0) - snapshots[0].balance
        except Exception:
            pass
        return {
            "balance": usdt.get("total", 0),
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
    return {"error": "strategy not found"}, 404


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
```

- [ ] **Step 2: Commit**

```bash
git add api/
git commit -m "feat: fastapi backend with REST + WebSocket endpoints"
```

---

## Task 11: 主入口 main.py

**Files:**
- Create: `main.py`

- [ ] **Step 1: 写 main.py**

```python
import asyncio
import logging
import uvicorn
from core.config import load_config
from core.data.fetcher import KlineFetcher
from core.data.stream import MarketStream
from core.risk.manager import RiskManager
from core.execution.engine import ExecutionEngine
from api.routes import app, set_engine, set_strategies
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_engine():
    config = load_config("config.yaml")
    exc_cfg = config.exchange

    fetcher = KlineFetcher(
        exc_cfg.id, exc_cfg.api_key, exc_cfg.secret, exc_cfg.password, exc_cfg.sandbox
    )
    stream = MarketStream(
        exc_cfg.id, exc_cfg.api_key, exc_cfg.secret, exc_cfg.password, exc_cfg.sandbox
    )
    risk = RiskManager(config.risk)
    execution = ExecutionEngine(exc_cfg, db_path=config.database.path)

    # 加载策略
    strategies = []
    for s_cfg in config.strategies:
        module_path, class_name = s_cfg.class_name.rsplit(".", 1) if "." in s_cfg.class_name else (f"strategies.{s_cfg.class_name.lower()}", s_cfg.class_name)
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError):
            # 尝试内置模板
            from core.strategy.templates import momentum, breakout
            templates = {"MomentumStrategy": momentum.MomentumStrategy, "BreakoutStrategy": breakout.BreakoutStrategy}
            cls = templates.get(s_cfg.class_name)
            if cls is None:
                logger.error(f"找不到策略类: {s_cfg.class_name}")
                continue
        strategy = cls(s_cfg.name, s_cfg.symbol, s_cfg.timeframe, s_cfg.params)
        strategies.append(strategy)
        logger.info(f"已加载策略: {s_cfg.name} ({s_cfg.symbol} {s_cfg.timeframe})")

    set_engine(execution)
    set_strategies(strategies)

    # 同步持仓
    await execution.sync_positions()

    # 注册行情回调
    async def on_bar(symbol, timeframe, df):
        for strategy in strategies:
            if not strategy.should_handle(symbol, timeframe):
                continue
            signal = strategy.on_bar(symbol, timeframe, df)
            if signal is None:
                continue
            # 更新风控账户状态
            try:
                bal = await execution.exchange.fetch_balance()
                usdt = bal.get("USDT", {})
                balance = usdt.get("total", 0.0)
                risk.update_account(balance=balance, daily_pnl=0.0, open_positions=len(execution._positions))
            except Exception:
                pass
            approved = risk.evaluate(signal)
            if approved:
                logger.info(f"信号审核通过: {signal.reason}")
                await execution.execute(approved)

    stream.on_bar(on_bar)

    # 启动 WebSocket 监听（每个 symbol/timeframe 组合）
    watch_tasks = set()
    for strategy in strategies:
        key = (strategy.symbol, strategy.timeframe)
        if key not in watch_tasks:
            watch_tasks.add(key)
            asyncio.create_task(stream.watch_candles(strategy.symbol, strategy.timeframe))

    logger.info("交易引擎已启动")
    await asyncio.Event().wait()  # 永久运行


async def main():
    config = load_config("config.yaml")
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level="info",
    ))
    await asyncio.gather(
        run_engine(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: main entry point with async engine + uvicorn"
```

---

## Task 12: React 前端

**Files:**
- Create: `web/` 目录（Vite + React + TailwindCSS）

- [ ] **Step 1: 初始化前端项目**

```bash
cd web
npm create vite@latest . -- --template react
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install recharts axios
```

- [ ] **Step 2: 配置 tailwind.config.js**

```js
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 3: 写主界面 web/src/App.jsx**

```jsx
import { useEffect, useState } from "react"
import axios from "axios"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

const API = "http://localhost:8080"

function StatCard({ title, value, sub }) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-1">
      <div className="text-gray-400 text-sm">{title}</div>
      <div className="text-white text-2xl font-bold">{value}</div>
      {sub && <div className="text-gray-500 text-xs">{sub}</div>}
    </div>
  )
}

function PositionRow({ pos }) {
  const isLong = pos.direction === "long"
  return (
    <tr className="border-t border-gray-700">
      <td className="py-2 text-white">{pos.symbol}</td>
      <td className={`py-2 font-semibold ${isLong ? "text-green-400" : "text-red-400"}`}>
        {isLong ? "多" : "空"}
      </td>
      <td className="py-2 text-gray-300">{pos.size}</td>
      <td className="py-2 text-gray-300">{pos.entry_price?.toFixed(2)}</td>
      <td className="py-2 text-red-400">{pos.stop_loss?.toFixed(2)}</td>
    </tr>
  )
}

export default function App() {
  const [account, setAccount] = useState({ balance: 0, available: 0 })
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [strategies, setStrategies] = useState([])

  const fetchData = async () => {
    try {
      const [acc, pos, ord, strat] = await Promise.all([
        axios.get(`${API}/api/account`),
        axios.get(`${API}/api/positions`),
        axios.get(`${API}/api/orders`),
        axios.get(`${API}/api/strategies`),
      ])
      setAccount(acc.data)
      setPositions(pos.data)
      setOrders(ord.data)
      setStrategies(strat.data)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  const pnlData = orders
    .filter(o => o.pnl !== null)
    .slice(0, 30)
    .reverse()
    .map((o, i) => ({ i, pnl: o.pnl }))

  const cumPnl = pnlData.reduce((acc, d, i) => {
    const prev = i === 0 ? 0 : acc[i - 1].cum
    return [...acc, { i: d.i, cum: prev + d.pnl }]
  }, [])

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <h1 className="text-2xl font-bold mb-6">币圈量化 Dashboard</h1>

      {/* 账户总览 */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <StatCard title="账户余额" value={`${account.balance?.toFixed(2) ?? 0} USDT`} />
        <StatCard title="可用余额" value={`${account.available?.toFixed(2) ?? 0} USDT`} />
        <StatCard title="持仓数" value={positions.length} sub={`策略数: ${strategies.length}`} />
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* 当前持仓 */}
        <div className="bg-gray-800 rounded-xl p-4">
          <h2 className="font-semibold mb-3">当前持仓</h2>
          {positions.length === 0 ? (
            <div className="text-gray-500 text-sm">暂无持仓</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-left">
                  <th className="pb-2">品种</th><th>方向</th><th>张数</th><th>入场价</th><th>止损</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => <PositionRow key={i} pos={p} />)}
              </tbody>
            </table>
          )}
        </div>

        {/* 收益曲线 */}
        <div className="bg-gray-800 rounded-xl p-4">
          <h2 className="font-semibold mb-3">累计收益曲线</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={cumPnl}>
              <XAxis dataKey="i" hide />
              <YAxis />
              <Tooltip formatter={(v) => [`${v.toFixed(2)} USDT`]} />
              <Line type="monotone" dataKey="cum" stroke="#22c55e" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 策略状态 */}
      <div className="bg-gray-800 rounded-xl p-4 mb-6">
        <h2 className="font-semibold mb-3">策略状态</h2>
        <div className="flex flex-wrap gap-3">
          {strategies.map(s => (
            <div key={s.id} className="bg-gray-700 rounded-lg px-3 py-2 flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${s.enabled ? "bg-green-400" : "bg-red-400"}`} />
              <span className="text-sm">{s.id}</span>
              <span className="text-gray-400 text-xs">{s.symbol} {s.timeframe}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 历史订单 */}
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="font-semibold mb-3">历史订单（最近100笔）</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 text-left">
              <th className="pb-2">品种</th><th>方向</th><th>张数</th><th>入场</th><th>出场</th><th>盈亏</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            {orders.map(o => (
              <tr key={o.id} className="border-t border-gray-700">
                <td className="py-1 text-white">{o.symbol}</td>
                <td className={`py-1 ${o.direction === "long" ? "text-green-400" : "text-red-400"}`}>{o.direction === "long" ? "多" : "空"}</td>
                <td className="py-1 text-gray-300">{o.size}</td>
                <td className="py-1 text-gray-300">{o.entry_price?.toFixed(2)}</td>
                <td className="py-1 text-gray-300">{o.exit_price?.toFixed(2) ?? "-"}</td>
                <td className={`py-1 font-semibold ${(o.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {o.pnl != null ? `${o.pnl.toFixed(2)}` : "-"}
                </td>
                <td className="py-1 text-gray-400 text-xs">{o.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 更新 web/src/index.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  background-color: #111827;
}
```

- [ ] **Step 5: 构建前端**

```bash
cd web && npm run build
```

- [ ] **Step 6: Commit**

```bash
cd ..
git add web/
git commit -m "feat: react dashboard with positions, orders, strategy status"
```

---

## Task 13: 全量测试 + 验证

- [ ] **Step 1: 运行所有测试**

```bash
pytest tests/ -v
```

期望：所有测试 PASSED

- [ ] **Step 2: 验证可启动（沙盒模式）**

确认 `config.yaml` 中 `sandbox: true` 且 API 密钥已填写，然后：

```bash
python main.py
```

期望：
- `INFO ... 交易引擎已启动`
- Web Dashboard 可访问 `http://localhost:8080`

- [ ] **Step 3: 运行一次简单回测验证**

```python
# 临时脚本 test_backtest_run.py
import asyncio
from core.data.fetcher import KlineFetcher
from core.strategy.templates.breakout import BreakoutStrategy
from core.backtest.engine import BacktestEngine
from core.config import RiskConfig, ExchangeConfig

async def main():
    cfg = ExchangeConfig(id="okx", sandbox=True)
    fetcher = KlineFetcher(cfg.id, sandbox=True)
    df = await fetcher.fetch_ohlcv("BTC-USDT-SWAP", "1h", limit=500)
    await fetcher.close()

    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 20})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(df)

    print(f"交易次数: {len(result.trades)}")
    print(f"总收益: {result.total_return:.2%}")
    print(f"胜率: {result.win_rate:.2%}")
    print(f"最大回撤: {result.max_drawdown:.2%}")

asyncio.run(main())
```

```bash
python test_backtest_run.py
```

- [ ] **Step 4: 最终 Commit**

```bash
git add .
git commit -m "chore: final integration verified"
```
