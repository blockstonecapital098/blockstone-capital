"""
MarketScanner scans approved symbols for basic price‑action signals.
It checks price change %, volume change, spread quality and emits a
:class:`SignalEvent` when a notable movement is detected.
"""

from __future__ import annotations

import logging
from typing import List

from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class MarketScanner(BaseAgent):
    """Simple scanner that looks for large price moves and spread anomalies.

    It runs on every incoming :class:`MarketSnapshot` and emits a signal only
    when the change exceeds configured thresholds.
    """

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="MarketScanner",
            department=AgentDepartment.SCANNER,
            event_bus=event_bus,
        )
        # Configurable thresholds – could be loaded from Settings later
        self.price_change_pct = 0.02  # 2 % move
        self.volume_change_pct = 0.30  # 30 % volume spike
        self.max_spread_pct = 0.01  # 1 % spread

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        # Guard against missing data
        if not snapshot.candles:
            raise DataUnavailableError("No candle data in snapshot")
        # Use the most recent candle (assume list sorted by time)
        latest = snapshot.candles[-1]
        # Simple percentage change from previous close (if we have at least 2 candles)
        if len(snapshot.candles) < 2:
            return None
        prev = snapshot.candles[-2]
        price_change = (latest.close - prev.close) / prev.close
        volume_change = (latest.volume - prev.volume) / prev.volume if prev.volume else 0.0
        spread = (snapshot.ticker.get("ask", 0) - snapshot.ticker.get("bid", 0)) / snapshot.ticker.get("mid", 0) if snapshot.ticker else 0.0
        evidence: List[str] = []
        direction: SignalDirection | None = None
        if abs(price_change) >= self.price_change_pct:
            direction = SignalDirection.UP if price_change > 0 else SignalDirection.DOWN
            evidence.append(f"price_change={price_change:.2%}")
        if abs(volume_change) >= self.volume_change_pct:
            evidence.append(f"volume_spike={volume_change:.2%}")
        if spread and spread > self.max_spread_pct:
            evidence.append(f"high_spread={spread:.2%}")
        if direction and evidence:
            signal = self._create_signal(
                symbol=latest.symbol,
                direction=direction,
                confidence=min(1.0, abs(price_change) * 5),  # simple confidence scaling
                evidence=evidence,
                market_regime="unknown",  # placeholder, real regime comes later
            )
            await self._publish(signal)
            return signal
        return None

# End of MarketScanner
