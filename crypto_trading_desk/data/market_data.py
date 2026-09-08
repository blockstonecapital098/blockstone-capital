"""
MarketDataManager streams live market data via CCXT Pro.
It maintains rolling windows of candles per symbol/timeframe and provides snapshots.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import ccxt
import ccxt.pro as ccxtpro

from crypto_trading_desk.core.models import Candle, MarketSnapshot
from crypto_trading_desk.core.events import MarketSnapshot as MarketSnapshotEvent
from crypto_trading_desk.core.event_bus import EventBus
from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class MarketDataManager:
    """Manages live market data streams using CCXT Pro.

    Features:
        - WebSocket connections for candles, orderbooks, tickers, trades.
        - Automatic reconnection on disconnect.
        - In‑memory rolling buffers (deque) for recent candles.
        - Generates :class:`MarketSnapshot` objects for downstream agents.
    """

    def __init__(self, event_bus: EventBus, settings: Settings | None = None):
        self.event_bus = event_bus
        self.settings = settings or Settings()
        self._exchanges: Dict[str, ccxtpro.Exchange] = {}
        self._running = False
        # buffers: symbol -> timeframe -> deque[Candle]
        self._candle_buffers: Dict[str, Dict[str, deque[Candle]]] = defaultdict(lambda: defaultdict(deque))
        # Configurable max candle history per timeframe
        self._max_candles = 500
        self._tasks: List[asyncio.Task] = []

    # ---------------------------------------------------------------------
    # Exchange handling
    # ---------------------------------------------------------------------
    def _create_exchange(self, name: str) -> ccxtpro.Exchange:
        cfg = getattr(self.settings, f"{name}_api_key", "")
        secret = getattr(self.settings, f"{name}_api_secret", "")
        testnet = getattr(self.settings, f"{name}_testnet", True)
        exchange_class = getattr(ccxtpro, name)
        return exchange_class({
            "apiKey": cfg,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "adjustForTimeDifference": True},
            "sandboxMode": testnet,
        })

    # ---------------------------------------------------------------------
    # Public lifecycle methods
    # ---------------------------------------------------------------------
    async def start(self, symbols: List[str] | None = None) -> None:
        """Start all data streams.

        Args:
            symbols: Optional explicit list of symbols to monitor.
                     If ``None`` the manager will use ``ASSET_CONFIG``
                     from the config package.
        """
        if self._running:
            logger.warning("MarketDataManager already running")
            return
        self._running = True
        symbols = symbols or []
        # Initialize exchange (currently only Binance is configured as default)
        binance = self._create_exchange("binance")
        self._exchanges["binance"] = binance
        # Start candle streams for each symbol/timeframe
        for symbol in symbols:
            for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
                task = asyncio.create_task(self._candle_worker(binance, symbol, tf))
                self._tasks.append(task)
        logger.info("MarketDataManager started for %d symbols", len(symbols))

    async def stop(self) -> None:
        """Stop all streaming tasks and close exchange connections."""
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for exch in self._exchanges.values():
            await exch.close()
        logger.info("MarketDataManager stopped")

    # ---------------------------------------------------------------------
    # Candle streaming worker
    # ---------------------------------------------------------------------
    async def _candle_worker(self, exchange: ccxtpro.Exchange, symbol: str, timeframe: str) -> None:
        while self._running:
            try:
                # ccxt.pro returns list of OHLCV: [ts, open, high, low, close, volume]
                ohlcv = await exchange.watch_ohlcv(symbol, timeframe)
                # Take the last candle (most recent)
                ts, o, h, l, c, v = ohlcv[-1]
                candle = Candle(
                    timestamp=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                buf = self._candle_buffers[symbol][timeframe]
                buf.append(candle)
                if len(buf) > self._max_candles:
                    buf.popleft()
                # Emit MarketSnapshot event every time a new candle arrives
                await self._publish_snapshot(symbol)
            except Exception as exc:
                logger.exception("Candle stream error %s %s: %s", symbol, timeframe, exc)
                await asyncio.sleep(1)  # back‑off before reconnect

    # ---------------------------------------------------------------------
    # Snapshot generation
    # ---------------------------------------------------------------------
    async def _publish_snapshot(self, symbol: str) -> None:
        """Create a MarketSnapshot from the buffered candles and publish it.

        The snapshot includes the most recent candle for each timeframe and the
        latest ticker information (price, spread, etc.).
        """
        # Collect latest candles per timeframe
        candles: List[Candle] = []
        for tf, buf in self._candle_buffers[symbol].items():
            if buf:
                candles.append(buf[-1])
        # Retrieve ticker (mid price, spread, volume)
        ticker = None
        try:
            binance = self._exchanges["binance"]
            raw = await binance.fetch_ticker(symbol)
            ticker = {
                "bid": raw.get("bid"),
                "ask": raw.get("ask"),
                "last": raw.get("last"),
                "bid_volume": raw.get("bidVolume"),
                "ask_volume": raw.get("askVolume"),
            }
        except Exception as exc:
            logger.debug("Failed to fetch ticker for %s: %s", symbol, exc)
        snapshot = MarketSnapshot(
            symbol=symbol,
            timestamp=datetime.now(tz=timezone.utc),
            candles=candles,
            ticker=ticker,
        )
        # Publish via the event bus – agents subscribe to MarketSnapshotEvent
        await self.event_bus.publish(MarketSnapshotEvent(snapshot=snapshot))

    # ---------------------------------------------------------------------
    # Public data accessors
    # ---------------------------------------------------------------------
    def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[Candle]:
        """Return the last *limit* candles for a given symbol/timeframe.

        This is a fast in‑memory read; it never hits the exchange.
        """
        buf = self._candle_buffers.get(symbol, {}).get(timeframe, deque())
        return list(buf)[-limit:]

    async def get_ticker(self, symbol: str) -> dict | None:
        """Fetch the most recent ticker from the exchange (async)."""
        try:
            binance = self._exchanges["binance"]
            return await binance.fetch_ticker(symbol)
        except Exception as exc:
            logger.debug("Ticker fetch failed for %s: %s", symbol, exc)
            return None

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict | None:
        """Fetch the order‑book snapshot (async)."""
        try:
            binance = self._exchanges["binance"]
            return await binance.fetch_order_book(symbol, limit=limit)
        except Exception as exc:
            logger.debug("Orderbook fetch failed for %s: %s", symbol, exc)
            return None

# End of MarketDataManager
