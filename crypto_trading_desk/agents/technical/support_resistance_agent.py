"""
SupportResistanceAgent detects swing highs and lows and key breakout levels.
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


class SupportResistanceAgent(BaseAgent):
    """Detects horizontal support/resistance zones and breakouts."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="SupportResistanceAgent",
            department=AgentDepartment.TECHNICAL,
            event_bus=event_bus,
        )
        self.lookback = 20

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

        for tf in ("4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < self.lookback:
                    continue
            except Exception:
                continue

            recent_high = df["high"].iloc[-self.lookback:-1].max()
            recent_low = df["low"].iloc[-self.lookback:-1].min()
            curr_close = df["close"].iloc[-1]

            direction = None
            confidence = 0.0

            if curr_close > recent_high:
                direction = SignalDirection.UP
                evidence.append(f"{tf}: Breakout above {self.lookback}-period resistance high ({curr_close:.2f} > {recent_high:.2f})")
                confidence = 0.70
            elif curr_close < recent_low:
                direction = SignalDirection.DOWN
                evidence.append(f"{tf}: Breakdown below {self.lookback}-period support low ({curr_close:.2f} < {recent_low:.2f})")
                confidence = 0.70

            if direction and confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime="support_resistance",
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
