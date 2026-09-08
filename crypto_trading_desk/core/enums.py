"""
Core enums used throughout the trading desk.
"""
from __future__ import annotations
from enum import Enum


class SignalDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    REGIME = "regime"
    VOLATILE = "volatile"


class AgentDepartment(str, Enum):
    TECHNICAL = "technical"
    REGIME = "regime"
    DERIVATIVES = "derivatives"
    ONCHAIN = "onchain"
    INTELLIGENCE = "intelligence"
    SCANNER = "scanner"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
