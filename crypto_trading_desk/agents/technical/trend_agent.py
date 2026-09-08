"""
TrendAgent analyses EMA crossovers, SMA200 and ADX to infer market trend.
Built with pure pandas & numpy for maximum reliability and zero external C-dependencies.
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


class TrendAgent(BaseAgent):
    """Detects medium-term trend using EMA crossovers, SMA200 and ADX."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(
            agent_id=agent_id,
            name="TrendAgent",
            department=AgentDepartment.TECHNICAL,
            event_bus=event_bus,
        )
        self.adx_threshold = 25
        self.ema_fast = 9
        self.ema_slow = 21
        self.sma_long = 200

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

    def _compute_adx(self, df: pd.DataFrame, length: int = 14) -> float:
        """Pure-pandas calculation of ADX (Average Directional Index)."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(length).mean()

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(length).mean() / (atr + 1e-9))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(length).mean() / (atr + 1e-9))

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
        adx = dx.rolling(length).mean()
        return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 20.0

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        best_confidence = 0.0
        best_signal: SignalEvent | None = None
        evidence: List[str] = []

        for tf in ("1h", "4h", "1d"):
            try:
                df = self._candles_to_df(snapshot, tf)
                if len(df) < self.sma_long:
                    continue
            except Exception:
                continue

            ema_fast = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
            ema_slow = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
            sma_long = df["close"].rolling(window=self.sma_long).mean()
            adx_val = self._compute_adx(df, length=14)

            direction = None
            if ema_fast.iloc[-1] > ema_slow.iloc[-1] and df["close"].iloc[-1] > sma_long.iloc[-1]:
                direction = SignalDirection.UP
                evidence.append(f"{tf}: EMA{self.ema_fast}>EMA{self.ema_slow}, Price>SMA{self.sma_long}")
            elif ema_fast.iloc[-1] < ema_slow.iloc[-1] and df["close"].iloc[-1] < sma_long.iloc[-1]:
                direction = SignalDirection.DOWN
                evidence.append(f"{tf}: EMA{self.ema_fast}<EMA{self.ema_slow}, Price<SMA{self.sma_long}")

            if direction and adx_val >= self.adx_threshold:
                confidence = min(1.0, (adx_val / 100.0) * 1.3)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_signal = self._create_signal(
                        symbol=snapshot.symbol,
                        direction=direction,
                        confidence=confidence,
                        evidence=evidence,
                        market_regime="trend",
                    )

        if best_signal:
            await self._publish(best_signal)
            return best_signal
        return None
