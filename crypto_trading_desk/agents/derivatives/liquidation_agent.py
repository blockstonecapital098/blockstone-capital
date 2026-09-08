"""
LiquidationAgent tracks liquidation cascades and liquidations heatmap levels.
Emits reversal signals when excessive long or short liquidations happen.
"""
from __future__ import annotations
import logging
from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class LiquidationAgent(BaseAgent):
    """Detects liquidation cascades and exhaustion bottoms/tops."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(agent_id, "LiquidationAgent", AgentDepartment.DERIVATIVES, event_bus)
        self.cascade_threshold_usd = 5_000_000 # $5M liquidations

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        long_liq = getattr(snapshot, "long_liquidations_usd", 0.0) or 0.0
        short_liq = getattr(snapshot, "short_liquidations_usd", 0.0) or 0.0

        if long_liq >= self.cascade_threshold_usd:
            # Long squeeze exhaustion -> Contrarian bounce long
            evidence = [f"Massive long liquidation cascade detected (${long_liq:,.0f}) - Seller exhaustion"]
            confidence = min(0.95, long_liq / (self.cascade_threshold_usd * 4))
            signal = self._create_signal(snapshot.symbol, SignalDirection.UP, confidence, evidence, "liq_cascade_bounce")
            await self._publish(signal)
            return signal
        elif short_liq >= self.cascade_threshold_usd:
            # Short squeeze exhaustion -> Contrarian drop short
            evidence = [f"Massive short squeeze cascade detected (${short_liq:,.0f}) - Buyer exhaustion"]
            confidence = min(0.95, short_liq / (self.cascade_threshold_usd * 4))
            signal = self._create_signal(snapshot.symbol, SignalDirection.DOWN, confidence, evidence, "short_squeeze_exhaustion")
            await self._publish(signal)
            return signal

        return None
