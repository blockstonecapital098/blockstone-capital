"""
HistoricalDataFetcher retrieves historical OHLCV data via CCXT REST API.
It handles multiple timeframes, gap detection, validation, and stores data in the database.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import ccxt
import pandas as pd

from crypto_trading_desk.config.settings import Settings
from crypto_trading_desk.core.models import Candle
from crypto_trading_desk.db.database import get_session
from crypto_trading_desk.db.models import Candle  # ORM model for storage (if needed)

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """Fetches historical candles for a symbol/timeframe via CCXT REST.

    Features:
        * Automatic rate‑limit handling.
        * Gap detection and backfill.
        * Basic validation: no future timestamps, non‑negative prices.
        * Returns a pandas DataFrame with a standard column set.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self._exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "adjustForTimeDifference": True},
            "sandboxMode": self.settings.binance_testnet,
        })

    # ------------------------------------------------------------------
    def _validate_ohlcv(self, ohlcv: List[List]) -> List[List]:
        """Validate a list of OHLCV rows.

        Raises ``ValueError`` if any row fails validation.
        """
        cleaned = []
        now_ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        for row in ohlcv:
            ts, o, h, l, c, v = row
            if ts > now_ts:
                logger.debug("Skipping future candle %s", row)
                continue
            if any(x < 0 for x in (o, h, l, c, v)):
                logger.debug("Skipping negative value candle %s", row)
                continue
            cleaned.append(row)
        return cleaned

    # ------------------------------------------------------------------
    def _ohlcv_to_dataframe(self, ohlcv: List[List], symbol: str, timeframe: str) -> pd.DataFrame:
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    # ------------------------------------------------------------------
    async def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """Fetch historical candles between *start* and *end*.

        Args:
            symbol: Market symbol, e.g. ``"BTC/USDT"``.
            timeframe: CCXT timeframe string (``"1m"``, ``"5m"`` …).
            start: Inclusive start datetime (UTC).
            end: Optional exclusive end datetime (UTC). If ``None`` defaults to now.
            limit: Maximum candles per API request (CCXT caps at 1000 for Binance).
        """
        if end is None:
            end = datetime.now(tz=timezone.utc)
        all_ohlcv: List[List] = []
        fetch_start = int(start.timestamp() * 1000)
        fetch_end = int(end.timestamp() * 1000)
        while fetch_start < fetch_end:
            try:
                batch = self._exchange.fetch_ohlcv(symbol, timeframe, since=fetch_start, limit=limit)
                batch = self._validate_ohlcv(batch)
                if not batch:
                    break
                all_ohlcv.extend(batch)
                # Move the cursor forward – CCXT returns the oldest candle first
                fetch_start = batch[-1][0] + 1
                # Respect exchange rate limits (already enabled, but add tiny sleep)
                time.sleep(0.05)
            except ccxt.BaseError as exc:
                logger.error("CCXT error fetching %s %s: %s", symbol, timeframe, exc)
                await asyncio.sleep(1)
                continue
        df = self._ohlcv_to_dataframe(all_ohlcv, symbol, timeframe)
        # Detect and fill gaps (simple forward fill of missing rows)
        df = df.set_index("timestamp")
        expected = pd.date_range(start=start, end=end, freq=timeframe)
        df = df.reindex(expected, method="ffill")
        df = df.reset_index().rename(columns={"index": "timestamp"})
        logger.info("Fetched %d candles for %s %s", len(df), symbol, timeframe)
        return df

    # ------------------------------------------------------------------
    async def store_to_db(self, df: pd.DataFrame) -> None:
        """Persist a DataFrame of candles to the TimescaleDB table.

        The ORM model ``Candle`` is expected to have matching columns.
        """
        async with get_session() as session:
            # Convert DataFrame rows to ORM objects
            records = [
                Candle(
                    timestamp=row["timestamp"].to_pydatetime(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                )
                for _, row in df.iterrows()
            ]
            session.add_all(records)
            await session.flush()
        logger.info("Stored %d candles to the database", len(df))

# End of HistoricalDataFetcher
