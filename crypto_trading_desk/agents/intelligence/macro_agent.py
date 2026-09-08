"""
MacroAgent monitors macroeconomic indicators (DXY, 10Y Yields, S&P 500, Nasdaq, Gold).
Weakening DXY / lowering yields = Risk-on / Bullish crypto.
Spiking DXY / rising yields = Risk-off / Bearish crypto.
"""
from __future__ import annotations
import logging
from crypto_trading_desk.core.enums import AgentDepartment, SignalDirection
from crypto_trading_desk.core.models import MarketSnapshot, SignalEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class MacroAgent(BaseAgent):
    """Correlates macro environment data to generate crypto market regime bias."""

    def __init__(self, agent_id: str, event_bus: EventBus):
        super().__init__(agent_id, "MacroAgent", AgentDepartment.INTELLIGENCE, event_bus)

    async def analyze(self, snapshot: MarketSnapshot) -> SignalEvent | None:
        macro = getattr(snapshot, "macro_data", None)
        if not macro:
            return None

        evidence = []
        bullish_pts = 0
        bearish_pts = 0

        # DXY trend check
        dxy_change = getattr(macro, "dxy_change_pct", 0.0) or 0.0
        if dxy_change < -0.003: # DXY falling > 0.3%
            bullish_pts += 1
            evidence.append(f"DXY weakening ({dxy_change:.2%}) - Dollar liquidity expansion")
        elif dxy_change > 0.003: # DXY surging > 0.3%
            bearish_pts += 1
            evidence.append(f"DXY surging ({dxy_change:.2%}) - Dollar liquidity contraction")

        # Equities check (S&P 500 / Nasdaq)
        sp500_change = getattr(macro, "sp500_change_pct", 0.0) or 0.0
        if sp500_change > 0.008:
            bullish_pts += 1
            evidence.append(f"US Equities rallying (+{sp500_change:.2%}) - Risk-on sentiment")
        elif sp500_change < -0.008:
            bearish_pts += 1
            evidence.append(f"US Equities selling off ({sp500_change:.2%}) - Risk-off sentiment")

        if bullish_pts > bearish_pts and bullish_pts > 0:
            confidence = min(0.9, bullish_pts * 0.4)
            signal = self._create_signal(snapshot.symbol, SignalDirection.UP, confidence, evidence, "macro_risk_on")
            await self._publish(signal)
            return signal
        elif bearish_pts > bullish_pts and bearish_pts > 0:
            confidence = min(0.9, bearish_pts * 0.4)
            signal = self._create_signal(snapshot.symbol, SignalDirection.DOWN, confidence, evidence, "macro_risk_off")
            await self._publish(signal)
            return signal

        return None
