"""
TradePostMortemGenerator produces a structured analysis of every closed trade.

It records entry, exit, slippage, fee, P&L, trade duration, and the original signals
that led to the trade, making the system fully auditable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PostMortem:
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: int
    fee_paid: float
    pnl: float
    duration_seconds: float
    entry_time: datetime
    exit_time: datetime
    signals: List[str] = field(default_factory=list)
    notes: str = ""

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * (1 if self.side == "buy" else -1)


class TradePostMortemGenerator:
    """Generates and stores post‑mortem records for closed trades."""

    def __init__(self):
        self._records: List[PostMortem] = []
        logger.info("TradePostMortemGenerator initialised")

    def generate(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        fee_paid: float,
        entry_time: datetime,
        exit_time: datetime,
        signals: Optional[List[str]] = None,
        notes: str = "",
    ) -> PostMortem:
        pnl = (exit_price - entry_price) * quantity * (1 if side == "buy" else -1) - fee_paid
        duration = (exit_time - entry_time).total_seconds()
        pm = PostMortem(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            fee_paid=fee_paid,
            pnl=pnl,
            duration_seconds=duration,
            entry_time=entry_time,
            exit_time=exit_time,
            signals=signals or [],
            notes=notes,
        )
        self._records.append(pm)
        logger.info(
            "PostMortem: %s %s %s | P&L=%.2f (%.2f%%) dur=%.0fs",
            trade_id, symbol, side, pnl, pm.pnl_pct * 100, duration,
        )
        return pm

    def all_records(self) -> List[PostMortem]:
        return list(self._records)

    def latest(self, n: int = 10) -> List[PostMortem]:
        return self._records[-n:]
