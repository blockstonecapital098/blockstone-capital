"""
VolatilityAgent computes ATR, Bollinger Bands and historical volatility.
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


class VolatilityAgent(BaseAgent):
    """Detects volatility expansion or contraction using ATR and Bollinger Bands."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="VolatilityAgent",
            department=AgentDepartment.TECHNICAL,
            event_bus=event_bus,
        )
        self.atr_period = 14
        self.bb_period = 20
        self.bb_std = 2

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

    def _compute_atr(self, df: pd.DataFrame, length: int = 14) -> float:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(length).mean()
        return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        evidence: List[str] = []
        best_signal: SignalEvent | None = None
        best_confidence = 0.0

        for tf in ("1h", "4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < self.bb_period:
                    continue
            except Exception:
                continue

            atr_val = self._compute_atr(df, length=self.atr_period)
            rolling_mean = df["close"].rolling(self.bb_period).mean()
            rolling_std = df["close"].rolling(self.bb_period).std()
            upper_band = rolling_mean + (rolling_std * self.bb_std)
            lower_band = rolling_mean - (rolling_std * self.bb_std)

            curr_price = df["close"].iloc[-1]
            direction = None
            confidence = 0.0

            if curr_price > upper_band.iloc[-1]:
                direction = SignalDirection.UP
                evidence.append(f"{tf}: Price breaking upper Bollinger Band ({curr_price:.2f} > {upper_band.iloc[-1]:.2f})")
                confidence = 0.75
            elif curr_price < lower_band.iloc[-1]:
                direction = SignalDirection.DOWN
                evidence.append(f"{tf}: Price breaking lower Bollinger Band ({curr_price:.2f} < {lower_band.iloc[-1]:.2f})")
                confidence = 0.75

            if direction and confidence > best_confidence:
                best_confidence = confidence
                best_signal = self._create_signal(
                    symbol=snapshot.symbol,
                    direction=direction,
                    confidence=confidence,
                    evidence=evidence.copy(),
                    market_regime="volatility",
                )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
