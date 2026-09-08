"""
SQLAlchemy ORM models for all trading desk entities:
Agents, Signals, Orders, Fills, Positions, RiskEvents, PostMortems, MarketSnapshots.
"""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    Text,
    JSON,
)
from crypto_trading_desk.db.database import Base


class DBSignal(Base):
    __tablename__ = "signals"

    id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), index=True)
    agent_name = Column(String(64))
    department = Column(String(32))
    symbol = Column(String(32), index=True)
    direction = Column(String(16))
    confidence = Column(Float)
    evidence = Column(JSON)
    market_regime = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class DBOrder(Base):
    __tablename__ = "orders"

    order_id = Column(String(64), primary_key=True)
    symbol = Column(String(32), index=True)
    side = Column(String(16))
    quantity = Column(Integer)
    notional = Column(Float)
    order_type = Column(String(32), default="market")
    status = Column(String(32), default="open", index=True)
    filled_qty = Column(Integer, default=0)
    avg_fill_price = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBRiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(String(64), primary_key=True)
    event_type = Column(String(64), index=True) # e.g. "KILL_SWITCH", "LIMIT_BREACH"
    reason = Column(Text)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBPostMortem(Base):
    __tablename__ = "trade_postmortems"

    trade_id = Column(String(64), primary_key=True)
    symbol = Column(String(32))
    side = Column(String(16))
    entry_price = Column(Float)
    exit_price = Column(Float)
    quantity = Column(Integer)
    fee_paid = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    duration_seconds = Column(Float)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
