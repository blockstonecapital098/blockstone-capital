"""
SentimentAgent analyzes market fear & greed index and social sentiment metrics.
Extreme fear with bottom divergence = contrarian long.
Extreme greed with top divergence = contrarian short.
"""
from __future__ import annotations
import logging
from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class SentimentAgent(BaseAgent):
    """Analyzes market sentiment (Fear & Greed Index, social volume)."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(agent_id, "SentimentAgent", AgentDepartment.INTELLIGENCE, event_bus)

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        sentiment_score = getattr(snapshot, "fear_and_greed_score", None) # 0 to 100
        if sentiment_score is None:
            return None

        direction = None
        evidence = []
        confidence = 0.0

        if sentiment_score < 20: # Extreme Fear -> Contrarian Buy
            direction = SignalDirection.UP
            confidence = (25 - sentiment_score) / 25.0 * 0.85
            evidence.append(f"Extreme Fear detected (Score: {sentiment_score}/100) - Contrarian accumulation signal")
        elif sentiment_score > 80: # Extreme Greed -> Contrarian Sell / Take Profit
            direction = SignalDirection.DOWN
            confidence = (sentiment_score - 75) / 25.0 * 0.85
            evidence.append(f"Extreme Greed detected (Score: {sentiment_score}/100) - Overbought distribution signal")

        if direction:
            signal = self._create_signal(snapshot.symbol, direction, confidence, evidence, "sentiment")
            await self._publish(signal)
            return signal

        return None
