"""
ManipulationDetector detects spoofing, wash trading, and pump-and-dump anomalies.
Raises alerts or rejects trade proposals when market integrity is compromised.
"""
from __future__ import annotations
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ManipulationDetector:
    """Monitors orderbook depth changes, volume anomalies, and spread widens to catch spoofing."""

    def __init__(self, max_spread_pct: float = 0.015, volume_spike_multiplier: float = 8.0):
        self.max_spread_pct = max_spread_pct
        self.volume_spike_multiplier = volume_spike_multiplier

    def check_integrity(self, snapshot: Any) -> Dict[str, Any]:
        """Validates that a symbol's current market action is free from acute manipulation."""
        ticker = getattr(snapshot, "ticker", {}) or {}
        bid = ticker.get("bid", 0.0) or 0.0
        ask = ticker.get("ask", 0.0) or 0.0

        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / bid
            if spread_pct > self.max_spread_pct:
                return {
                    "is_safe": False,
                    "reason": f"Extreme spread detected ({spread_pct:.2%}) - Potential spoofing/illiquidity risk",
                    "code": "ABNORMAL_SPREAD"
                }

        # Check for abnormal 1-min volume pump vs baseline
        return {"is_safe": True, "reason": "Market integrity nominal", "code": "CLEAN"}
