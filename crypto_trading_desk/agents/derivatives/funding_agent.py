"""
FundingAgent monitors perpetual swap funding rates and emits a signal when rates exceed a threshold, indicating potential short‑bias.
"""

from __future__ import annotations

import logging
from typing import List

from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class FundingAgent(BaseAgent):
    """Simple funding‑rate monitor.

    If the funding rate for the symbol is above ``funding_threshold`` (positive) we emit a
    bearish signal (short bias). If it is below ``-funding_threshold`` we emit a bullish
    signal. Confidence is proportional to the absolute rate.
    """

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="FundingAgent",
            department=AgentDepartment.DERIVATIVES,
            event_bus=event_bus,
        )
        self.funding_threshold = 0.0005  # 0.05 %

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        # The snapshot is expected to contain a ``funding_rate`` attribute (float) for the symbol.
        funding = getattr(snapshot, "funding_rate", None)
        if funding is None:
            logger.debug("FundingAgent: no funding_rate present in snapshot")
            return None
        direction = None
        if funding > self.funding_threshold:
            direction = SignalDirection.DOWN
            evidence = [f"Funding rate {funding:.5f} > threshold"]
            confidence = min(1.0, funding / (self.funding_threshold * 4))
        elif funding < -self.funding_threshold:
            direction = SignalDirection.UP
            evidence = [f"Funding rate {funding:.5f} < -threshold"]
            confidence = min(1.0, -funding / (self.funding_threshold * 4))
        else:
            return None
        signal = self._create_signal(
            symbol=snapshot.symbol,
            direction=direction,
            confidence=confidence,
            evidence=evidence,
            market_regime="funding",
        )
        await self._publish(signal)
        return signal

# End of FundingAgent
