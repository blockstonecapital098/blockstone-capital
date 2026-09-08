"""
MomentumAgent computes RSI, MACD and Stochastic indicators.
Built with pure pandas & numpy for maximum reliability and speed.
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


class MomentumAgent(BaseAgent):
    """Detects momentum extremes and divergences using RSI, MACD and Stochastic."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="MomentumAgent",
            department=AgentDepartment.TECHNICAL,
            event_bus=event_bus,
        )
        self.rsi_overbought = 70
        self.rsi_oversold = 30
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9

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

    def _compute_rsi(self, close: pd.Series, length: int = 14) -> float:
        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=length).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

    def _compute_macd_hist(self, close: pd.Series) -> float:
        fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=self.macd_signal, adjust=False).mean()
        hist = macd - signal
        return float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else 0.0

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        evidence: List[str] = []
        best_signal: SignalEvent | None = None
        best_confidence = 0.0

        for tf in ("1h", "4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < 30:
                    continue
            except Exception:
                continue

            rsi_val = self._compute_rsi(df["close"], length=14)
            macd_hist = self._compute_macd_hist(df["close"])

            direction = None
            confidence = 0.0

            if rsi_val > self.rsi_overbought and macd_hist < 0:
                direction = SignalDirection.DOWN
                evidence.append(f"{tf}: RSI={rsi_val:.1f} (Overbought), MACD Histogram turning negative")
                confidence = min(1.0, (rsi_val - self.rsi_overbought) / 25.0 + 0.5)
            elif rsi_val < self.rsi_oversold and macd_hist > 0:
                direction = SignalDirection.UP
                evidence.append(f"{tf}: RSI={rsi_val:.1f} (Oversold), MACD Histogram turning positive")
                confidence = min(1.0, (self.rsi_oversold - rsi_val) / 25.0 + 0.5)

            if direction and confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime="momentum",
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
