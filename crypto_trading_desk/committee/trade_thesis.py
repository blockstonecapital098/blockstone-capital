"""
Trade thesis agents: BullCaseAgent, BearCaseAgent, and DevilsAdvocateAgent.
These debate every prospective trade opportunity, stress-testing both sides before execution.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class BullCaseAgent:
    """Builds the strongest empirical case in favor of going long or holding."""

    def formulate_thesis(self, signals: List[Any]) -> Dict[str, Any]:
        bull_signals = [s for s in signals if getattr(s, "direction", "").lower() in ["up", "buy"]]
        points = []
        for s in bull_signals:
            points.extend(getattr(s, "evidence", []))

        avg_conf = sum(getattr(s, "confidence", 0.0) for s in bull_signals) / max(1, len(bull_signals)) if bull_signals else 0.0
        return {
            "side": "BULL",
            "support_count": len(bull_signals),
            "confidence": round(avg_conf, 3),
            "arguments": points or ["No strong bullish structural evidence."]
        }


class BearCaseAgent:
    """Builds the strongest empirical case in favor of shorting or staying in cash."""

    def formulate_thesis(self, signals: List[Any]) -> Dict[str, Any]:
        bear_signals = [s for s in signals if getattr(s, "direction", "").lower() in ["down", "sell"]]
        points = []
        for s in bear_signals:
            points.extend(getattr(s, "evidence", []))

        avg_conf = sum(getattr(s, "confidence", 0.0) for s in bear_signals) / max(1, len(bear_signals)) if bear_signals else 0.0
        return {
            "side": "BEAR",
            "support_count": len(bear_signals),
            "confidence": round(avg_conf, 3),
            "arguments": points or ["No strong bearish breakdown evidence."]
        }


class DevilsAdvocateAgent:
    """Specifically searches for blindspots, counter-trends, and failure modes in a proposed trade."""

    def challenge_thesis(self, proposed_side: str, signals: List[Any]) -> Dict[str, Any]:
        opposing_side = "down" if proposed_side.lower() in ["up", "buy"] else "up"
        counter_signals = [s for s in signals if getattr(s, "direction", "").lower() == opposing_side]
        risks = []

        for s in counter_signals:
            for ev in getattr(s, "evidence", []):
                risks.append(f"Conflict warning: {ev}")

        return {
            "challenge_status": "HIGH_RISK" if len(counter_signals) >= 2 else "ACCEPTED",
            "counter_signal_count": len(counter_signals),
            "critical_risks": risks or ["No severe cross-department signal conflicts detected."]
        }
