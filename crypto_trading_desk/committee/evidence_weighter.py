"""
EvidenceWeighter dynamically weights signals from various departments to avoid duplicate correlation bias.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any
from crypto_trading_desk.core.enums import AgentDepartment

logger = logging.getLogger(__name__)


class EvidenceWeighter:
    """Groups signals by department and assigns diversified weighting."""

    DEPARTMENT_BASE_WEIGHTS = {
        AgentDepartment.TECHNICAL: 0.25,
        AgentDepartment.DERIVATIVES: 0.25,
        AgentDepartment.ONCHAIN: 0.20,
        AgentDepartment.INTELLIGENCE: 0.15,
        AgentDepartment.REGIME: 0.15,
    }

    def weigh_signals(self, signals: List[Any]) -> Dict[str, float]:
        """Calculates weighted consensus direction."""
        dept_scores = {"UP": 0.0, "DOWN": 0.0}
        seen_depts = set()

        for s in signals:
            dept = getattr(s, "department", AgentDepartment.TECHNICAL)
            dir_str = str(getattr(s, "direction", "UP")).upper()
            if "UP" in dir_str:
                clean_dir = "UP"
            elif "DOWN" in dir_str:
                clean_dir = "DOWN"
            else:
                continue

            conf = getattr(s, "confidence", 0.5)
            w = self.DEPARTMENT_BASE_WEIGHTS.get(dept, 0.2)

            # Downweight duplicate signals within the same department to prevent clustering
            if dept in seen_depts:
                w *= 0.5
            seen_depts.add(dept)

            dept_scores[clean_dir] += conf * w

        return dept_scores
