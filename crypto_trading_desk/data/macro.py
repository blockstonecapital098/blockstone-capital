"""
MacroDataFetcher retrieves macro-economic indicators using free public APIs (Yahoo Finance) and provides simple trend calculations.
It caches results to avoid excessive calls.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx
import pandas as pd

from crypto_trading_desk.core.models import MacroData
from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class MacroDataFetcher:
    """Fetch macro data such as DXY, US Treasury yields, S&P 500, Nasdaq, Gold.

    Uses Yahoo Finance CSV download endpoints (no API key required). Results are cached for ``cache_ttl`` seconds.
    """

    _YAHOO_URL = "https://query1.finance.yahoo.com/v7/finance/download/{symbol}"

    def __init__(self, settings: Settings | None = None, cache_ttl: int = 300):
        self.settings = settings or Settings()
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple[float, MacroData]] = {}
        self._client = httpx.AsyncClient(timeout=10)

    async def _download(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        params = {
            "period1": "0",  # start from epoch
            "period2": str(int(time.time())),
            "interval": interval,
            "events": "history",
        }
        url = self._YAHOO_URL.format(symbol=symbol)
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            df = pd.read_csv(pd.compat.StringIO(resp.text), parse_dates=["Date"], index_col="Date")
            return df
        except Exception as exc:
            logger.debug("Failed to download {symbol} from Yahoo: %s", exc)
            return pd.DataFrame()

    async def get_macro(self, name: str) -> Optional[MacroData]:
        """Return cached macro data for *name* (e.g. "DXY", "US10Y", "SPX", "NDX", "GC=F")."""
        now = time.time()
        if name in self._cache and now < self._cache[name][0]:
            return self._cache[name][1]

        symbol_map = {
            "DXY": "DX-Y.NYB",  # Dollar Index
            "US10Y": "^TNX",   # 10‑year Treasury yield
            "SPX": "^GSPC",   # S&P 500
            "NDX": "^IXIC",   # Nasdaq Composite
            "GOLD": "GC=F",   # Gold futures
        }
        yahoo_symbol = symbol_map.get(name)
        if not yahoo_symbol:
            logger.warning("Macro name %s not mapped to a Yahoo symbol", name)
            return None
        df = await self._download(yahoo_symbol)
        if df.empty:
            return None
        latest = df.iloc[-1]
        macro = MacroData(
            name=name,
            value=latest.get("Close"),
            timestamp=datetime.fromtimestamp(int(latest.name.timestamp()), tz=timezone.utc),
        )
        self._cache[name] = (now + self.cache_ttl, macro)
        return macro

    async def close(self) -> None:
        await self._client.aclose()

# End of MacroDataFetcher
