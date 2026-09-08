"""
Order Management System (OMS).

Tracks the lifecycle of every order from creation through fill or cancellation.
Provides helper methods for the executor and paper engine.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from crypto_trading_desk.core.models import TradeProposal
from crypto_trading_desk.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class Order:
    """Represents a single order in the system."""

    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    def __init__(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        notional: float,
        order_type: str = "market",
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.notional = notional
        self.order_type = order_type
        self.status = self.OPEN
        self.filled_qty = 0
        self.avg_fill_price = 0.0
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def fill(self, qty: int, price: float) -> None:
        self.filled_qty += qty
        self.avg_fill_price = price
        if self.filled_qty >= self.quantity:
            self.status = self.FILLED
        self.updated_at = datetime.now(timezone.utc)

    def cancel(self) -> None:
        self.status = self.CANCELLED
        self.updated_at = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, symbol={self.symbol}, "
            f"side={self.side}, qty={self.quantity}, status={self.status})"
        )


class OMS:
    """In‑memory order management system.

    Creates orders from ``TradeProposal`` events and tracks their status.
    In a live environment this would persist to the database via ``get_session``.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._orders: Dict[str, Order] = {}
        self.event_bus.subscribe(TradeProposal, self._handle_proposal)
        logger.info("OMS subscribed to TradeProposal events")

    async def _handle_proposal(self, proposal: TradeProposal) -> None:
        order = self.create_order(proposal)
        logger.info("OMS created order %s", order)
        await self.event_bus.publish(order)

    def create_order(self, proposal: TradeProposal) -> Order:
        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            notional=proposal.notional,
        )
        self._orders[order_id] = order
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def open_orders(self) -> List[Order]:
        return [o for o in self._orders.values() if o.status == Order.OPEN]

    def all_orders(self) -> List[Order]:
        return list(self._orders.values())
