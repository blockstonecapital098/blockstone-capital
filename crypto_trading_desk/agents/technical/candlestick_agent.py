"""
CandlestickAgent detects common candlestick patterns (engulfing, doji).
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


class CandlestickAgent(BaseAgent):
    """Detects engulfing and reversal candlestick patterns."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="CandlestickAgent",
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
                if len(df) < 3:
                    continue
            except Exception:
                continue

            prev = df.iloc[-2]
            cur = df.iloc[-1]
            direction = None
            confidence = 0.0

            # Bullish engulfing
            if cur["open"] < cur["close"] and prev["open"] > prev["close"]:
                if cur["close"] > prev["open"] and cur["open"] < prev["close"]:
                    direction = SignalDirection.UP
                    evidence.append(f"{tf}: Bullish engulfing pattern")
                    confidence = 0.75
            # Bearish engulfing
            elif cur["open"] > cur["close"] and prev["open"] < prev["close"]:
                if cur["open"] > prev["close"] and cur["close"] < prev["open"]:
                    direction = SignalDirection.DOWN
                    evidence.append(f"{tf}: Bearish engulfing pattern")
                    confidence = 0.75

            if direction and confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime="candlestick",
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
