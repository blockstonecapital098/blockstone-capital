"""
State persistence module — saves and loads portfolio state across server restarts.
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    STATE_FILE = "/tmp/portfolio_state.json"
else:
    STATE_FILE = os.path.join(os.getcwd(), "portfolio_state.json")


def save_state(portfolio: Any) -> None:
    """Serializes essential portfolio state to JSON."""
    try:
        data = {
            "realized_pnl": getattr(portfolio, "realized_pnl", 0.0),
            "positions": getattr(portfolio, "positions", {}),
            "total_exposure": getattr(portfolio, "total_exposure", 0.0),
            "entry_prices": getattr(portfolio, "_entry_prices", {}),
            "closed_trades": getattr(portfolio, "closed_trades", []),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("Portfolio state saved to %s", STATE_FILE)
    except Exception as exc:
        logger.error("Failed to save portfolio state: %s", exc)


def load_state(portfolio: Any) -> None:
    """Restores portfolio state from JSON if available."""
    if not os.path.exists(STATE_FILE):
        logger.info("No prior portfolio state found. Starting fresh.")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        portfolio.realized_pnl = data.get("realized_pnl", 0.0)
        portfolio.positions = data.get("positions", {})
        portfolio.total_exposure = data.get("total_exposure", 0.0)
        portfolio._entry_prices = data.get("entry_prices", {})
        portfolio.closed_trades = data.get("closed_trades", [])
        logger.info("Successfully restored portfolio state from %s", STATE_FILE)
    except Exception as exc:
        logger.error("Failed to load portfolio state: %s", exc)
