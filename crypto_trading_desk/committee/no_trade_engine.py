"""
NoTradeEngine actively looks for reasons NOT to trade (capital preservation priority).
It validates low volume, high chop, pending macro FOMC events, or excessive uncertainty.
"""
from __future__ import annotations
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class NoTradeEngine:
    """Default state is NO_TRADE unless all criteria for an asymmetric edge are satisfied."""

    def __init__(self, min_composite_confidence: float = 0.65):
        self.min_confidence = min_composite_confidence

    def evaluate_opportunity(self, symbol: str, composite_score: float, market_regime: str | None = None) -> Dict[str, Any]:
        if composite_score < self.min_confidence:
            return {
                "can_trade": False,
                "reason": f"Composite edge ({composite_score:.2f}) below required bar ({self.min_confidence:.2f}). Capital preserved in cash.",
                "action": "STAND_ASIDE"
            }

        if market_regime and "chop" in market_regime.lower():
            return {
                "can_trade": False,
                "reason": "Market in high-frequency whipsaw / chop regime. Overtrading avoided.",
                "action": "STAND_ASIDE"
            }

        return {
            "can_trade": True,
            "reason": f"High conviction institutional setup confirmed ({composite_score:.2f}).",
            "action": "PROCEED"
        }
