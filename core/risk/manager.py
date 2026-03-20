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

        size = risk_amount / price_risk

        # 4. 杠杆检查（简化：名义价值 / 余额）
        notional = size * signal.entry_price
        leverage = notional / self._account_balance
        if leverage > self.config.max_leverage:
            size = (self._account_balance * self.config.max_leverage) / signal.entry_price
            leverage = self.config.max_leverage

        return ApprovedSignal(signal=signal, size=round(size, 4), leverage=round(leverage, 2))
