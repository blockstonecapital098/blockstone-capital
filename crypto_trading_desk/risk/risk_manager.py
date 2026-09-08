"""
HardRiskManager enforces hard risk limits (max position size, max drawdown, max leverage, etc.)
It provides a method `evaluate_proposal` that returns True if the trade is allowed, False otherwise.
"""

from __future__ import annotations

import logging
from typing import Optional

from crypto_trading_desk.config.risk_limits import RiskLimits
from crypto_trading_desk.core.models import TradeProposal, RiskDecision

logger = logging.getLogger(__name__)


class HardRiskManager:
    """Deterministic hard‑risk checks.

    The manager is stateless; it receives the current portfolio state and a
    ``TradeProposal`` and verifies it against the immutable ``RiskLimits``.
    If any limit is violated it returns a ``RiskDecision`` with ``allowed=False``
    and a reason string.
    """

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def evaluate_proposal(self, proposal: TradeProposal, portfolio) -> RiskDecision:
        """Evaluate a trade proposal against hard limits.

        Parameters
        ----------
        proposal: TradeProposal
            The trade the HeadTrader wants to execute.
        portfolio: Any
            An object exposing ``total_exposure``, ``position_size(symbol)`` and
            ``drawdown`` attributes (the concrete type is defined in the OMS).
        """
        # 1. Max position size per symbol
        current_size = portfolio.position_size(proposal.symbol)
        if proposal.quantity + current_size > self.limits.max_position_size:
            reason = f"Position size {proposal.quantity + current_size} exceeds max {self.limits.max_position_size}"
            logger.warning("HardRiskManager reject: %s", reason)
            return RiskDecision(allowed=False, reason=reason)
        # 2. Max total exposure
        if portfolio.total_exposure + proposal.notional > self.limits.max_total_exposure:
            reason = f"Total exposure {portfolio.total_exposure + proposal.notional} exceeds max {self.limits.max_total_exposure}"
            logger.warning("HardRiskManager reject: %s", reason)
            return RiskDecision(allowed=False, reason=reason)
        # 3. Max drawdown (absolute)
        if portfolio.drawdown and portfolio.drawdown > self.limits.max_drawdown:
            reason = f"Drawdown {portfolio.drawdown} exceeds max {self.limits.max_drawdown}"
            logger.warning("HardRiskManager reject: %s", reason)
            return RiskDecision(allowed=False, reason=reason)
        # 4. Max leverage
        if proposal.leverage and proposal.leverage > self.limits.max_leverage:
            reason = f"Leverage {proposal.leverage} exceeds max {self.limits.max_leverage}"
            logger.warning("HardRiskManager reject: %s", reason)
            return RiskDecision(allowed=False, reason=reason)
        # All checks passed
        return RiskDecision(allowed=True, reason="All hard limits satisfied")

# End of HardRiskManager
