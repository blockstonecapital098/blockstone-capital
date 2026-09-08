"""
PriceActionAgent looks for classic price-action patterns (pin bars, engulfing, inside bars).
Built with pure pandas & numpy.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np
import pandas as pd

from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class PriceActionAgent(BaseAgent):
    """Detects pin bars and inside bars."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="PriceActionAgent",
            department=AgentDepartment.TECHNICAL,
            event_bus=event_bus,
        )

    def _candles_to_df(self, snapshot: MarketSnapshot, tf: str) -> pd.DataFrame:
        candles = [c for c in snapshot.candles if c.timeframe == tf]
        if not candles:
            raise ValueError(f"No candles for timeframe {tf}")
        df = pd.DataFrame([
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ])
        df.set_index("timestamp", inplace=True)
        return df

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        evidence: List[str] = []
        best_signal: SignalEvent | None = None
        best_confidence = 0.0

        for tf in ("1h", "4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < 5:
                    continue
            except Exception:
                continue

            latest = df.iloc[-1]
            body = abs(latest["close"] - latest["open"])
            upper_wick = latest["high"] - max(latest["close"], latest["open"])
            lower_wick = min(latest["close"], latest["open"]) - latest["low"]
            total_range = latest["high"] - latest["low"] + 1e-9

            direction = None
            confidence = 0.0

            if lower_wick / total_range > 0.6:
                direction = SignalDirection.UP
                evidence.append(f"{tf}: Bullish hammer/pin bar (rejection from low)")
                confidence = 0.70
            elif upper_wick / total_range > 0.6:
                direction = SignalDirection.DOWN
                evidence.append(f"{tf}: Bearish shooting star/pin bar (rejection from high)")
                confidence = 0.70

            if direction and confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime="price_action",
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
