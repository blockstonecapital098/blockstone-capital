"""
TradeScorer scores prospective trades based on multi-agent consensus, conflict penalties, and R/R ratio.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class TradeScorer:
    """Calculates final composite trade score between 0.0 and 1.0."""

    def score_trade(self, primary_signal: Any, committee_debate: Dict[str, Any]) -> float:
        base_confidence = getattr(primary_signal, "confidence", 0.5)
        bull = committee_debate.get("bull", {})
        bear = committee_debate.get("bear", {})
        challenge = committee_debate.get("challenge", {})

        # Penalty if devil's advocate flags high risk
        penalty = 0.25 if challenge.get("challenge_status") == "HIGH_RISK" else 0.0

        # Consensus boost if multiple agents agree
        side = getattr(primary_signal, "direction", "").lower()
        agreed_count = bull.get("support_count", 0) if side in ["up", "buy"] else bear.get("support_count", 0)
        consensus_bonus = min(0.2, (agreed_count - 1) * 0.05) if agreed_count > 1 else 0.0

        final_score = max(0.0, min(1.0, base_confidence + consensus_bonus - penalty))
        return round(final_score, 3)
