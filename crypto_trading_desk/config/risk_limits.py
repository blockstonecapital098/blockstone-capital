"""
Immutable hard risk limits — these cannot be overridden at runtime.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    # Per-trade limits
    risk_per_trade: float = 0.05          # 5% of equity ($50 margin per trade)
    max_position_size: int = 5_000        # max qty per symbol
    max_notional_per_trade: float = 500.0 # max USD notional per trade ($50 margin x 10x lev = $500)

    # Portfolio limits
    max_total_exposure: float = 1500.0    # max total exposure
    max_drawdown: float = 150.0           # $150 drawdown triggers auto-halt (15%)

    # Leverage
    max_leverage: int = 10                # 10x leverage as requested

    # Stop-loss defaults
    default_stop_loss_pct: float = 0.02   # 2%
    default_take_profit_pct: float = 0.04 # 4% (2:1 R/R)


# Singleton — import this everywhere
RISK_LIMITS = RiskLimits()
