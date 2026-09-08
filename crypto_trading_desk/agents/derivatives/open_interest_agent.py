"""
OpenInterestAgent monitors the perpetual futures open‑interest level and emits a signal when it spikes.
"""

from __future__ import annotations

import logging
from typing import List

from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class OpenInterestAgent(BaseAgent):
    """Simple open‑interest monitor.

    If the open‑interest for the symbol rises more than ``oi_threshold`` (percentage)
    compared to the previous snapshot we emit a bullish signal (expecting continuation).
    """

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="OpenInterestAgent",
            department=AgentDepartment.DERIVATIVES,
            event_bus=event_bus,
        )
        self.oi_threshold = 0.10  # 10 % increase

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        # Expect snapshot to have ``open_interest`` and ``prev_open_interest`` attributes.
        oi = getattr(snapshot, "open_interest", None)
        prev_oi = getattr(snapshot, "prev_open_interest", None)
        if oi is None or prev_oi is None:
            logger.debug("OpenInterestAgent: missing open_interest data")
            return None
        change = (oi - prev_oi) / prev_oi if prev_oi != 0 else 0.0
        if change >= self.oi_threshold:
            evidence = [f"Open interest +{change:.2%} (threshold {self.oi_threshold:.2%})"]
            confidence = min(1.0, change * 5)
            signal = self._create_signal(
                symbol=snapshot.symbol,
                direction=SignalDirection.UP,
                confidence=confidence,
                evidence=evidence,
                market_regime="open_interest",
            )
            await self._publish(signal)
            return signal
        return None

# End of OpenInterestAgent
