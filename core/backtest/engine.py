from dataclasses import dataclass, field
from typing import Optional
import numpy as np
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
        hours = n_trades
        years = hours / 8760
        if years <= 0:
            return 0.0
        return (1 + self.total_return) ** (1 / years) - 1

    @property
    def sharpe_ratio(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        pnls = [t.pnl for t in self.trades]
        mean = np.mean(pnls)
        std = np.std(pnls)
        if std == 0:
            return 0.0
        return float(mean / std * (252 ** 0.5))


class BacktestEngine:
    def __init__(self, strategy: BaseStrategy, risk_config: RiskConfig, initial_balance: float = 10000.0):
        self.strategy = strategy
        self.risk = RiskManager(risk_config)
        self.initial_balance = initial_balance

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        逐根 K 线回测。
        df: 完整历史 K 线，index 为 timestamp，列为 open/high/low/close/volume
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

            entry_price = df["close"].iloc[i + 1] if i + 1 < len(df) else current_price
            open_trade = {
                "direction": signal.direction,
                "entry_price": entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "size": approved.size,
                "entry_idx": i,
            }

        result.final_balance = balance
        return result
