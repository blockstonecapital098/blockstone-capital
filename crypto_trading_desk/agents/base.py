"""
Abstract BaseAgent — all analysis agents inherit from this class.

Provides:
- Structured logging with agent name/department
- Helper to create a properly-typed SignalEvent
- Safe async publish (catches and logs errors without crashing)
- Lifecycle hooks (start/stop)
"""
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus


class BaseAgent(ABC):
    """Abstract base class for all analysis agents."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        department: AgentDepartment,
        event_bus: EventBus,
    ):
        self.agent_id = agent_id
        self.name = name
        self.department = department
        self.event_bus = event_bus
        self.logger = logging.getLogger(f"agent.{department.value}.{name}")
        self._running = False

    async def start(self) -> None:
        self._running = True
        self.logger.info("%s started", self.name)

    async def stop(self) -> None:
        self._running = False
        self.logger.info("%s stopped", self.name)

    @abstractmethod
    async def analyze(self, snapshot: MarketSnapshot) -> Optional[SignalEvent]:
        """Analyse a market snapshot and return a SignalEvent if warranted."""

    def _create_signal(
        self,
        symbol: str,
        direction: SignalDirection,
        confidence: float,
        evidence: List[str],
        market_regime: Optional[str] = None,
    ) -> SignalEvent:
        return SignalEvent(
            signal_id=str(uuid.uuid4()),
            agent_id=self.agent_id,
            agent_name=self.name,
            department=self.department,
            symbol=symbol,
            direction=direction,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            evidence=evidence,
            market_regime=market_regime,
            timestamp=datetime.now(timezone.utc),
        )

    async def _publish(self, signal: SignalEvent) -> None:
        try:
            await self.event_bus.publish(signal)
            self.logger.info(
                "Signal: %s %s conf=%.2f evidence=%s",
                signal.symbol,
                signal.direction.value,
                signal.confidence,
                "; ".join(signal.evidence[:2]),
            )
        except Exception as exc:
            self.logger.error("Failed to publish signal: %s", exc)
