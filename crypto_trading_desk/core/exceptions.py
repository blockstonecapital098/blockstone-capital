"""
Custom exception hierarchy for the trading desk.
"""
from __future__ import annotations


class TradingDeskError(Exception):
    """Base exception for all trading desk errors."""


# Risk exceptions
class RiskLimitError(TradingDeskError):
    """A hard risk limit was breached."""

class MaxDrawdownError(RiskLimitError):
    """Drawdown exceeded the maximum threshold."""

class MaxExposureError(RiskLimitError):
    """Total portfolio exposure exceeded maximum."""

class MaxLeverageError(RiskLimitError):
    """Requested leverage exceeds the allowed maximum."""

class PositionSizeError(RiskLimitError):
    """Order size exceeds the per-symbol position limit."""

class KillSwitchActivatedError(TradingDeskError):
    """The global kill-switch has been activated — all trading is halted."""

class EmergencyHaltError(TradingDeskError):
    """An emergency condition triggered an automatic trading halt."""


# Execution exceptions
class ExecutionError(TradingDeskError):
    """An error occurred during order execution."""

class OrderRejectedError(ExecutionError):
    """The exchange rejected the order."""

class SlippageExceededError(ExecutionError):
    """Actual slippage exceeded the maximum allowed slippage."""


# Data exceptions
class DataUnavailableError(TradingDeskError):
    """Required market data is not available."""

class StaleDataError(DataUnavailableError):
    """The available data is too old to be reliable."""


# Agent exceptions
class AgentError(TradingDeskError):
    """An agent encountered an error during analysis."""

class InsufficientDataError(AgentError):
    """The agent did not have enough data to produce a signal."""


# Security exceptions
class SecurityError(TradingDeskError):
    """A security check failed."""

class ManipulationDetectedError(SecurityError):
    """Potential market manipulation was detected."""
