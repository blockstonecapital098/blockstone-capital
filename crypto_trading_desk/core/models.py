"""
Core Pydantic models — the data contracts shared across every layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from crypto_trading_desk.core.enums import SignalDirection, AgentDepartment, MarketRegime


class Candle(BaseModel):
    timestamp: datetime
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketSnapshot(BaseModel):
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    candles: List[Candle] = Field(default_factory=list)
    ticker: Dict[str, Any] = Field(default_factory=dict)
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    prev_open_interest: Optional[float] = None


class SignalEvent(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    agent_name: str
    department: AgentDepartment
    symbol: str
    direction: SignalDirection
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    market_regime: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AggregatedSignal(BaseModel):
    symbol: str
    direction: SignalDirection
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    source_agents: List[str] = Field(default_factory=list)
    market_regime: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TradeProposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: str  # "buy" or "sell"
    quantity: int
    notional: float
    confidence: float
    leverage: int = 1
    evidence: List[str] = Field(default_factory=list)
    market_regime: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskDecision(BaseModel):
    allowed: bool
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    sentiment: Optional[str] = None  # positive, negative, neutral
    currencies: List[str] = Field(default_factory=list)


class MacroData(BaseModel):
    timestamp: datetime
    dxy: Optional[float] = None
    us10y: Optional[float] = None
    sp500: Optional[float] = None
    nasdaq: Optional[float] = None
    gold: Optional[float] = None
