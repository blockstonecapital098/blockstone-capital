"""
Executor routes filled orders to live exchange or paper engine based on trading mode.
"""

from __future__ import annotations

import logging

from crypto_trading_desk.config.settings import Settings
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.execution.oms import Order
from crypto_trading_desk.execution.exchange_adapter import ExchangeAdapter

logger = logging.getLogger(__name__)


class Executor:
    """Routes orders to the correct backend depending on trading mode.

    In **paper** mode the ``PaperEngine`` fills orders via event subscription,
    so ``Executor`` only handles **live** mode here.
    """

    def __init__(self, event_bus: EventBus, settings: Settings, adapter: ExchangeAdapter):
        self.event_bus = event_bus
        self.settings = settings
        self.adapter = adapter
        if self.settings.trading_mode == "live":
            self.event_bus.subscribe(Order, self._send_to_exchange)
            logger.info("Executor subscribed to Order events (live mode)")
        else:
            logger.info("Executor inactive – paper mode; PaperEngine handles fills")

    async def _send_to_exchange(self, order: Order) -> None:
        if order.status != Order.OPEN:
            return
        try:
            await self.adapter.place_order(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                amount=order.quantity,
            )
        except Exception as exc:
            logger.error("Executor failed to send order %s: %s", order.order_id, exc)
            order.cancel()
