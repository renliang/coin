import asyncio
import logging
import uvicorn
from core.config import load_config
from core.data.fetcher import KlineFetcher
from core.data.stream import MarketStream
from core.risk.manager import RiskManager
from core.execution.engine import ExecutionEngine
from api.routes import app, set_engine, set_strategies, set_db_path
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_engine():
    config = load_config("config.yaml")
    exc_cfg = config.exchange

    stream = MarketStream(
        exc_cfg.id, exc_cfg.api_key, exc_cfg.secret, exc_cfg.password, exc_cfg.sandbox
    )
    risk = RiskManager(config.risk)
    execution = ExecutionEngine(exc_cfg, db_path=config.database.path)

    set_db_path(config.database.path)

    # 加载策略
    strategies = []
    for s_cfg in config.strategies:
        cls = None
        if "." in s_cfg.class_name:
            module_path, class_name = s_cfg.class_name.rsplit(".", 1)
            try:
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
            except (ImportError, AttributeError):
                pass
        if cls is None:
            # 尝试内置模板
            from core.strategy.templates import momentum, breakout
            templates = {
                "MomentumStrategy": momentum.MomentumStrategy,
                "BreakoutStrategy": breakout.BreakoutStrategy,
            }
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
                logger.info(f"信号审核通过: {signal.symbol} {signal.direction} | {signal.reason}")
                await execution.execute(approved)

    stream.on_bar(on_bar)

    # 启动 WebSocket 监听（每个 symbol/timeframe 组合）
    watch_keys: set[tuple] = set()
    for strategy in strategies:
        key = (strategy.symbol, strategy.timeframe)
        if key not in watch_keys:
            watch_keys.add(key)
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
