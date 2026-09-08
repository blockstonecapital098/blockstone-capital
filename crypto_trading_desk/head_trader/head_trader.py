"""
HeadTrader receives aggregated signals, runs risk checks, and creates trade proposals.
It uses the HardRiskManager, PositionSizer, PortfolioMonitor and EmergencyManager.
Only proposals with confidence > CONF_THRESHOLD are considered.
"""

from __future__ import annotations

import logging
from typing import Optional

from crypto_trading_desk.core.models import AggregatedSignal, TradeProposal, RiskDecision
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.head_trader.signal_aggregator import SignalAggregator
from crypto_trading_desk.risk.risk_manager import HardRiskManager
from crypto_trading_desk.risk.position_sizer import PositionSizer
from crypto_trading_desk.risk.portfolio_monitor import PortfolioMonitor
from crypto_trading_desk.risk.emergency import EmergencyManager
from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class HeadTrader:
    """Core decision engine for the trading desk.

    Workflow:
    1. Subscribes to ``AggregatedSignal`` events from ``SignalAggregator``.
    2. Filters signals based on a confidence threshold.
    3. Checks emergency kill‑switch.
    4. Uses ``HardRiskManager`` and ``PositionSizer`` to evaluate and size the trade.
    5. Emits a ``TradeProposal`` on the ``EventBus`` for downstream components.
    """

    CONF_THRESHOLD = 0.6

    def __init__(self, event_bus: EventBus, risk_manager: HardRiskManager, sizer: PositionSizer, portfolio: PortfolioMonitor, emergency: EmergencyManager):
        self.event_bus = event_bus
        self.risk_manager = risk_manager
        self.sizer = sizer
        self.portfolio = portfolio
        self.emergency = emergency
        # Subscribe to aggregated signals
        self.event_bus.subscribe(AggregatedSignal, self._handle_aggregated)
        logger.info("HeadTrader subscribed to AggregatedSignal")

    async def _handle_aggregated(self, agg_signal: AggregatedSignal) -> None:
        if self.emergency.is_active:
            logger.warning("HeadTrader: emergency active – ignoring signal for %s", agg_signal.symbol)
            return
        if agg_signal.confidence < self.CONF_THRESHOLD:
            logger.debug("HeadTrader: signal confidence %.2f below threshold for %s", agg_signal.confidence, agg_signal.symbol)
            return
        # Simple stop‑loss distance assumption (e.g., 1% of price)
        # Require portfolio to provide ``price`` method – we use a placeholder
        price = getattr(self.portfolio, "price", lambda s: 1.0)(agg_signal.symbol)
        stop_loss_distance = price * 0.01
        qty, notional = self.sizer.size(agg_signal.symbol, stop_loss_distance, self.portfolio)
        if qty == 0:
            logger.info("HeadTrader: PositionSizer returned zero qty for %s", agg_signal.symbol)
            return
        proposal = TradeProposal(
            symbol=agg_signal.symbol,
            side="buy" if agg_signal.direction.name.lower() == "up" else "sell",
            quantity=qty,
            notional=notional,
            confidence=agg_signal.confidence,
            evidence=agg_signal.evidence,
            market_regime=agg_signal.market_regime,
            leverage=1,  # simple default
        )
        # Run hard risk check
        decision: RiskDecision = self.risk_manager.evaluate_proposal(proposal, self.portfolio)
        if not decision.allowed:
            logger.warning("HeadTrader: trade rejected by risk manager – %s", decision.reason)
            return
        # Publish proposal for approval / execution
        logger.info("HeadTrader: publishing TradeProposal for %s qty=%d", proposal.symbol, proposal.quantity)
        await self.event_bus.publish(proposal)

# End of HeadTrader
