"""
ExchangeAdapter wraps CCXT to provide a simple async interface for placing orders on live exchanges.
In paper‑trading mode it is bypassed entirely by PaperEngine.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    import ccxt.async_support as ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class ExchangeAdapter:
    """Thin async wrapper around a CCXT exchange instance.

    Used only in live trading mode (``Settings.trading_mode == "live"``).
    In paper mode the ``PaperEngine`` handles all fills.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._exchange: Any = None
        if CCXT_AVAILABLE:
            self._exchange = ccxt.binance({
                "apiKey": settings.binance_api_key,
                "secret": settings.binance_api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
            if settings.binance_testnet:
                self._exchange.set_sandbox_mode(True)
        else:
            logger.warning("ccxt not installed – ExchangeAdapter is disabled")

    async def place_order(self, symbol: str, side: str, order_type: str, amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        if self._exchange is None:
            raise RuntimeError("ccxt not available")
        params: Dict[str, Any] = {}
        try:
            result = await self._exchange.create_order(symbol, order_type, side, amount, price, params)
            logger.info("ExchangeAdapter placed %s %s %s qty=%.4f", side, order_type, symbol, amount)
            return result
        except Exception as exc:
            logger.error("ExchangeAdapter order failed for %s: %s", symbol, exc)
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        if self._exchange is None:
            raise RuntimeError("ccxt not available")
        return await self._exchange.cancel_order(order_id, symbol)

    async def close(self) -> None:
        if self._exchange:
            await self._exchange.close()
