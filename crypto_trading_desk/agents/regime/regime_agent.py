"""
RegimeAgent classifies market regime (Bull, Bear, Sideways, Volatile).
Built with pure pandas & numpy.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np
import pandas as pd

from crypto_trading_desk.core.enums import AgentDepartment, MarketRegime, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class RegimeAgent(BaseAgent):
    """Regime classifier evaluating volatility and trend strength."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="RegimeAgent",
            department=AgentDepartment.REGIME,
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

        for tf in ("4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < 20:
                    continue
            except Exception:
                continue

            price_change = (df["close"].iloc[-1] - df["close"].iloc[-20]) / df["close"].iloc[-20]
            direction = SignalDirection.UP if price_change > 0.03 else (SignalDirection.DOWN if price_change < -0.03 else SignalDirection.NEUTRAL)
            regime = "BULL_TREND" if price_change > 0.03 else ("BEAR_TREND" if price_change < -0.03 else "SIDEWAYS_CHOP")
            confidence = min(0.9, abs(price_change) * 5 + 0.4)
            evidence.append(f"{tf}: {regime} detected (20-period return: {price_change:.2%})")

            if confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime=regime,
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
