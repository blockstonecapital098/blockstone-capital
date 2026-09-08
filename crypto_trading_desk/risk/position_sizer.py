"""
PositionSizer calculates the exact order size for a trade based on risk parameters and portfolio state.
It returns the quantity and notional that satisfy the desired risk per trade.
"""

from __future__ import annotations

import logging
from typing import Tuple

from crypto_trading_desk.config.risk_limits import RiskLimits
from crypto_trading_desk.core.models import TradeProposal

logger = logging.getLogger(__name__)


class PositionSizer:
    """Size positions using a fixed risk‑per‑trade fraction.

    The sizer assumes the portfolio provides ``equity`` (total account value) and
    ``price(symbol)`` methods. The size is computed as:
        risk_amount = equity * risk_limits.risk_per_trade
        quantity = risk_amount / (stop_loss_distance * price)
    The resulting quantity is clipped to ``max_position_size``.
    """

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def size(self, symbol: str, stop_loss_distance: float, portfolio) -> Tuple[int, float]:
        """Return ``(quantity, notional)`` for the given ``symbol``.

        Parameters
        ----------
        symbol: str
            Trading symbol.
        stop_loss_distance: float
            Absolute price distance to the stop‑loss.
        portfolio: Any
            Must expose ``equity`` and ``price(symbol)``.
        """
        equity = getattr(portfolio, "equity", 0.0)
        price = portfolio.price(symbol)
        if price <= 0 or stop_loss_distance <= 0:
            logger.error("Invalid price or stop‑loss distance for %s", symbol)
            return 0, 0.0
        risk_amount = equity * self.limits.risk_per_trade
        raw_qty = risk_amount / (stop_loss_distance * price)
        # Clip to max position size
        max_qty = self.limits.max_position_size
        qty = int(min(raw_qty, max_qty))
        notional = qty * price
        logger.debug("PositionSizer: %s qty=%d notional=%.2f", symbol, qty, notional)
        return qty, notional

# End of PositionSizer
