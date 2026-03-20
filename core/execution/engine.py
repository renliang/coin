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
