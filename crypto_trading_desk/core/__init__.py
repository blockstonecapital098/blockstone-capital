"""
Core package — re-exports the most important types for convenience.
"""
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.core.enums import (
    SignalDirection, OrderStatus, MarketRegime, AgentDepartment, TradingMode
)
from crypto_trading_desk.core.models import (
    Candle, MarketSnapshot, SignalEvent, AggregatedSignal,
    TradeProposal, RiskDecision, NewsItem, MacroData
)
from crypto_trading_desk.core.exceptions import (
    TradingDeskError, KillSwitchActivatedError, RiskLimitError,
    DataUnavailableError, AgentError
)

__all__ = [
    "EventBus",
    "SignalDirection", "OrderStatus", "MarketRegime", "AgentDepartment", "TradingMode",
    "Candle", "MarketSnapshot", "SignalEvent", "AggregatedSignal",
    "TradeProposal", "RiskDecision", "NewsItem", "MacroData",
    "TradingDeskError", "KillSwitchActivatedError", "RiskLimitError",
    "DataUnavailableError", "AgentError",
]
