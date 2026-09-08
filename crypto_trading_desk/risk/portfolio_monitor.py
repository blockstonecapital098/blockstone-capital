"""
PortfolioMonitor keeps a lightweight view of current positions, exposure, equity and drawdown.
It provides helper methods for the risk manager and execution layer.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class PortfolioMonitor:
    """Simple in‑memory portfolio tracker.

    It stores position sizes per symbol and tracks equity, total exposure and max drawdown.
    The implementation is deliberately lightweight – for a production system you would
    persist state to a database and handle partial fills, P&L, etc.
    """

    def __init__(self, initial_equity: float = 1_000.0):
        self.equity = initial_equity
        self.positions: Dict[str, int] = {}
        self.high_watermark = initial_equity
        self.drawdown = 0.0
        self.total_exposure = 0.0

    # ----- Position helpers -----
    def position_size(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def update_position(self, symbol: str, quantity: int, price: float) -> None:
        """Add *quantity* (positive for long, negative for short) at *price*.

        Updates equity, exposure and drawdown.
        """
        prev_qty = self.positions.get(symbol, 0)
        new_qty = prev_qty + quantity
        self.positions[symbol] = new_qty
        notional = quantity * price
        self.equity -= notional  # simple cash‑accounting (ignore fees)
        self.total_exposure = sum(abs(q) * price for q, price in self._current_notional_items())
        # Update drawdown
        if self.equity > self.high_watermark:
            self.high_watermark = self.equity
        self.drawdown = self.high_watermark - self.equity
        logger.debug(
            "Portfolio updated %s: qty=%d, price=%.2f, equity=%.2f, drawdown=%.2f",
            symbol,
            new_qty,
            price,
            self.equity,
            self.drawdown,
        )

    def _current_notional_items(self):
        # Placeholder: in a real system you would store entry price per position.
        # Here we assume a flat price of 1 for simplicity.
        for symbol, qty in self.positions.items():
            yield qty, 1.0

    # ----- Query helpers -----
    @property
    def total_exposure(self) -> float:
        # Simple sum of absolute notional (using placeholder price 1.0)
        return sum(abs(q) * 1.0 for q in self.positions.values())

    @total_exposure.setter
    def total_exposure(self, value: float):  # pragma: no cover
        # Setter kept for compatibility with RiskManager expectations.
        pass

# End of PortfolioMonitor
