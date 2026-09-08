"""
NewsAgent processes incoming news headlines and emits directional signals.
Bullish news emits UP, bearish news emits DOWN.
"""
from __future__ import annotations
import logging
from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class NewsAgent(BaseAgent):
    """Parses news sentiment and keywords attached to the market snapshot."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(agent_id, "NewsAgent", AgentDepartment.INTELLIGENCE, event_bus)

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        news_items = getattr(snapshot, "news_items", []) or []
        if not news_items:
            return None

        bullish_count = 0
        bearish_count = 0
        evidence = []

        for item in news_items:
            sentiment = getattr(item, "sentiment", "").lower()
            title = getattr(item, "title", "")
            if sentiment == "positive" or any(w in title.lower() for w in ["etf", "approval", "rally", "partnership"]):
                bullish_count += 1
                evidence.append(f"Bullish news: {title[:60]}")
            elif sentiment == "negative" or any(w in title.lower() for w in ["hack", "ban", "lawsuit", "crash", "sec"]):
                bearish_count += 1
                evidence.append(f"Bearish news: {title[:60]}")

        if bullish_count > bearish_count and bullish_count >= 2:
            confidence = min(1.0, (bullish_count - bearish_count) * 0.3 + 0.4)
            signal = self._create_signal(snapshot.symbol, SignalDirection.UP, confidence, evidence, "news")
            await self._publish(signal)
            return signal
        elif bearish_count > bullish_count and bearish_count >= 2:
            confidence = min(1.0, (bearish_count - bullish_count) * 0.3 + 0.4)
            signal = self._create_signal(snapshot.symbol, SignalDirection.DOWN, confidence, evidence, "news")
            await self._publish(signal)
            return signal

        return None
