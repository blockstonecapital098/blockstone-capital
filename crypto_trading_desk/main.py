"""
Main orchestrator — starts all services and runs the FastAPI app.

Usage:
    python -m crypto_trading_desk.main
"""

from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting Crypto Multi‑Agent Trading Desk …")
    uvicorn.run(
        "crypto_trading_desk.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
