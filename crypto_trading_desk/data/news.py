"""
NewsDataClient fetches crypto news from CryptoPanic (or fallback).
It returns structured news items with source, title, url, published_at, currencies, sentiment.
Caching is provided to limit API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from crypto_trading_desk.core.models import NewsItem
from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class NewsDataClient:
    """Client for CryptoPanic news API.

    If the API key is not configured, the client returns an empty list and logs a warning.
    The result objects are instances of :class:`NewsItem` defined in ``core.models``.
    """

    def __init__(self, settings: Settings | None = None, cache_ttl: int = 300):
        self.settings = settings or Settings()
        self._cache_ttl = cache_ttl
        self._cache_expiry = 0.0
        self._cached: List[NewsItem] = []
        self._client = httpx.AsyncClient(timeout=10)

    # ------------------------------------------------------------------
    async def _fetch(self) -> List[NewsItem]:
        api_key = self.settings.cryptopanic_api_key
        if not api_key:
            logger.warning("CryptoPanic API key not set – news data will be unavailable")
            return []
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": api_key,
            "public": "true",
            "filter": "news",
            "kind": "news",
            "lang": "en",
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.debug("CryptoPanic request failed: %s", exc)
            return []
        items: List[NewsItem] = []
        for entry in data.get("results", []):
            # Basic parsing – more fields can be added later
            item = NewsItem(
                source=entry.get("domain", "unknown"),
                title=entry.get("title", ""),
                url=entry.get("url", ""),
                published_at=datetime.fromtimestamp(entry.get("published_at", 0), tz=timezone.utc),
                currencies=entry.get("currencies", []),
                sentiment=entry.get("sentiment", "neutral"),
            )
            items.append(item)
        return items

    # ------------------------------------------------------------------
    async def get_latest(self, force_refresh: bool = False) -> List[NewsItem]:
        """Return cached news items, refreshing if the cache is stale.

        Args:
            force_refresh: Bypass the cache and request fresh data.
        """
        now = time.time()
        if force_refresh or now >= self._cache_expiry:
            self._cached = await self._fetch()
            self._cache_expiry = now + self._cache_ttl
        return self._cached

    async def close(self) -> None:
        await self._client.aclose()

# End of NewsDataClient
