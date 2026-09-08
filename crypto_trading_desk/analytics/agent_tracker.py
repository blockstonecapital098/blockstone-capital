"""
AgentPerformanceTracker records signal accuracy per agent over time.

For each fill event it checks whether the fill direction matched the agent's
original signal direction. Tracks hit‑rate and P&L contribution per agent.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class AgentStats:
    agent_id: str
    total_signals: int = 0
    correct_signals: int = 0
    total_pnl: float = 0.0
    signal_history: List[Dict] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        if self.total_signals == 0:
            return 0.0
        return self.correct_signals / self.total_signals


class AgentPerformanceTracker:
    """Lightweight in‑memory tracker.

    In production, stats should be persisted via ``get_session`` into the
    ``agent_performance`` table.  Here we keep everything in RAM for V1.
    """

    def __init__(self):
        self._stats: Dict[str, AgentStats] = defaultdict(lambda s="": AgentStats(agent_id=s))

    def record_signal(self, agent_id: str, symbol: str, direction: str, confidence: float) -> None:
        stats = self._stats.setdefault(agent_id, AgentStats(agent_id=agent_id))
        stats.total_signals += 1
        stats.signal_history.append(
            {"symbol": symbol, "direction": direction, "confidence": confidence, "outcome": None}
        )
        logger.debug("AgentTracker recorded signal from %s (%s %s %.2f)", agent_id, symbol, direction, confidence)

    def record_outcome(self, agent_id: str, correct: bool, pnl: float) -> None:
        stats = self._stats.setdefault(agent_id, AgentStats(agent_id=agent_id))
        if correct:
            stats.correct_signals += 1
        stats.total_pnl += pnl
        # Update the last unresolved signal
        for entry in reversed(stats.signal_history):
            if entry["outcome"] is None:
                entry["outcome"] = "correct" if correct else "incorrect"
                entry["pnl"] = pnl
                break
        logger.debug("AgentTracker updated outcome for %s correct=%s pnl=%.2f", agent_id, correct, pnl)

    def get_stats(self, agent_id: str) -> AgentStats:
        return self._stats.get(agent_id, AgentStats(agent_id=agent_id))

    def all_stats(self) -> Dict[str, AgentStats]:
        return dict(self._stats)

    def summary(self) -> List[Dict]:
        return [
            {
                "agent_id": s.agent_id,
                "total_signals": s.total_signals,
                "hit_rate": round(s.hit_rate, 4),
                "total_pnl": round(s.total_pnl, 2),
            }
            for s in self._stats.values()
        ]
