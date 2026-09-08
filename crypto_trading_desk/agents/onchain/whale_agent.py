"""
WhaleAgent monitors on‑chain large transfers (whale movements) and emits directional signals.
Large inflows to exchanges = bearish. Large outflows from exchanges = bullish.
"""
from __future__ import annotations
import logging
from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class WhaleAgent(BaseAgent):
    """Detects whale movements from on-chain data attached to the snapshot.

    Expects ``snapshot.whale_inflow`` and ``snapshot.whale_outflow`` floats (USD).
    """

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(agent_id, "WhaleAgent", AgentDepartment.ONCHAIN, event_bus)
        self.threshold_usd = 10_000_000  # $10M movement threshold

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        inflow = getattr(snapshot, "whale_inflow", 0.0) or 0.0
        outflow = getattr(snapshot, "whale_outflow", 0.0) or 0.0

        if inflow > self.threshold_usd:
            evidence = [f"Whale inflow to exchange: ${inflow:,.0f} (bearish signal)"]
            confidence = min(1.0, inflow / (self.threshold_usd * 5))
            signal = self._create_signal(snapshot.symbol, SignalDirection.DOWN, confidence, evidence, "onchain")
            await self._publish(signal)
            return signal

        if outflow > self.threshold_usd:
            evidence = [f"Whale outflow from exchange: ${outflow:,.0f} (bullish signal)"]
            confidence = min(1.0, outflow / (self.threshold_usd * 5))
            signal = self._create_signal(snapshot.symbol, SignalDirection.UP, confidence, evidence, "onchain")
            await self._publish(signal)
            return signal

        return None
