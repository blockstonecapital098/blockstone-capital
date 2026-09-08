"""
SignalAggregator collects SignalEvents from agents, groups them by symbol and market regime, and produces a consolidated signal.
For simplicity it selects the signal with the highest confidence per symbol.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from crypto_trading_desk.core.models import SignalEvent, AggregatedSignal
from crypto_trading_desk.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SignalAggregator:
    """Aggregates raw signals into a single per‑symbol signal.

    The aggregator subscribes to ``SignalEvent``. For each symbol it keeps the
    highest‑confidence signal (could be extended with weighting, de‑duplication,
    etc.). When a new best signal is set it publishes an ``AggregatedSignal``.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._best_signals: Dict[str, SignalEvent] = {}
        # Register handler
        self.event_bus.subscribe(SignalEvent, self._handle_signal)
        logger.info("SignalAggregator subscribed to SignalEvent")

    async def _handle_signal(self, signal: SignalEvent) -> None:
        symbol = signal.symbol
        current_best = self._best_signals.get(symbol)
        if current_best is None or signal.confidence > current_best.confidence:
            self._best_signals[symbol] = signal
            agg = AggregatedSignal(
                symbol=symbol,
                direction=signal.direction,
                confidence=signal.confidence,
                evidence=signal.evidence,
                source_agents=[signal.agent_id],
            )
            logger.debug("SignalAggregator publishing aggregated signal for %s", symbol)
            await self.event_bus.publish(agg)

    def get_best(self, symbol: str) -> Optional[SignalEvent]:
        return self._best_signals.get(symbol)

# End of SignalAggregator
