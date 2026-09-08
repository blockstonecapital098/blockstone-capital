"""
Paper Trading Engine — simulates order fills with realistic slippage and fees.

Formula:
    exec_price = mid * (1 + spread_factor * direction)
    spread_factor = base_spread + alpha * (size / depth) ^ beta
    fee = notional * taker_fee
"""

from __future__ import annotations

import logging
import math
import random
from typing import Tuple

from crypto_trading_desk.execution.oms import Order
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.risk.portfolio_monitor import PortfolioMonitor

logger = logging.getLogger(__name__)


class PaperEngine:
    """Simulates trade execution in paper‑trading mode.

    Configuration
    -------------
    base_spread   : half‑spread in price fraction (default 0.0002 = 0.02 %)
    alpha         : market‑impact scaling factor
    beta          : market‑impact exponent
    taker_fee     : taker fee as a fraction (default 0.0005 = 0.05 %)
    maker_fee     : maker fee fraction
    depth         : assumed order‑book depth in notional USD
    """

    def __init__(
        self,
        event_bus: EventBus,
        portfolio: PortfolioMonitor,
        base_spread: float = 0.0002,
        alpha: float = 0.01,
        beta: float = 0.5,
        taker_fee: float = 0.0005,
        maker_fee: float = 0.0002,
        depth: float = 1_000_000.0,
    ):
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.base_spread = base_spread
        self.alpha = alpha
        self.beta = beta
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.depth = depth
        # Subscribe to Order events from OMS
        self.event_bus.subscribe(Order, self._fill_order)
        logger.info("PaperEngine subscribed to Order events")

    def _slippage(self, side: str, notional: float) -> float:
        """Return the fractional slippage for this order."""
        impact = self.alpha * math.pow(notional / self.depth, self.beta)
        spread = self.base_spread + impact
        return spread if side == "buy" else -spread

    async def _fill_order(self, order: Order) -> None:
        if order.status != Order.OPEN:
            return
        # Mid price from portfolio (placeholder)
        mid = getattr(self.portfolio, "_prices", {}).get(order.symbol, 1.0)
        slippage = self._slippage(order.side, order.notional)
        exec_price = mid * (1 + slippage)
        fee = order.notional * self.taker_fee
        order.fill(order.quantity, exec_price)
        self.portfolio.update_position(order.symbol, order.quantity if order.side == "buy" else -order.quantity, exec_price)
        logger.info(
            "PaperEngine filled %s %s x%d @ %.4f (fee %.2f)",
            order.side,
            order.symbol,
            order.quantity,
            exec_price,
            fee,
        )
        # Publish fill event for downstream (analytics, alerts)
        await self.event_bus.publish({"type": "fill", "order": order, "price": exec_price, "fee": fee})
