"""
OnChainDataClient integrates with Glassnode and CryptoQuant APIs to fetch on‑chain metrics.
It provides cached, typed results for exchange flows, MVRV, SOPR, reserves, funding rates, and open interest.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import httpx

from crypto_trading_desk.core.models import (
    ExchangeFlow,
    MVRVData,
    SOPRData,
    ReserveData,
    FundingRateData,
    OpenInterestData,
)
from crypto_trading_desk.config.settings import Settings

logger = logging.getLogger(__name__)


class _CacheEntry:
    def __init__(self, value, expires_at: float):
        self.value = value
        self.expires_at = expires_at

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


class OnChainDataClient:
    """Client for Glassnode and CryptoQuant on‑chain data.

    The class gracefully degrades when API keys are missing – it logs a warning
    and returns ``None`` so that downstream agents can continue without raising
    an exception (the system treats missing on‑chain data as a *non‑critical* loss).
    """

    def __init__(self, settings: Settings | None = None, cache_ttl: int = 300):
        self.settings = settings or Settings()
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._client = httpx.AsyncClient(timeout=10)

    # ------------------------------------------------------------------
    async def _request(self, url: str, params: dict) -> Optional[dict]:
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.debug("HTTP request failed %s %s", url, exc)
            return None

    # ------------------------------------------------------------------
    def _cache_get(self, key: str) -> Optional[object]:
        entry = self._cache.get(key)
        if entry and entry.is_valid():
            return entry.value
        self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, value: object) -> None:
        self._cache[key] = _CacheEntry(value, time.time() + self._cache_ttl)

    # ------------------------------------------------------------------
    async def get_exchange_flows(self, asset: str) -> Optional[ExchangeFlow]:
        """Fetch net exchange flow (in/out) for *asset* from Glassnode.

        Returns ``ExchangeFlow`` model or ``None`` if unavailable.
        """
        cached = self._cache_get(f"flows:{asset}")
        if cached:
            return cached
        if not self.settings.glassnode_api_key:
            logger.warning("Glassnode API key not configured; exchange flow unavailable for %s", asset)
            return None
        url = "https://api.glassnode.com/v1/metrics/transactions/exchange_netflow"
        params = {"api_key": self.settings.glassnode_api_key, "a": asset}
        data = await self._request(url, params)
        if not data:
            return None
        # Assume API returns list of dicts sorted by timestamp, we take the latest
        latest = data[-1]
        flow = ExchangeFlow(asset=asset, net_flow=latest.get("v"), timestamp=datetime.fromtimestamp(latest.get("t"), tz=timezone.utc))
        self._cache_set(f"flows:{asset}", flow)
        return flow

    # ------------------------------------------------------------------
    async def get_mvrv(self, asset: str) -> Optional[MVRVData]:
        if not self.settings.glassnode_api_key:
            logger.warning("Glassnode API key missing for MVRV data")
            return None
        cached = self._cache_get(f"mvrv:{asset}")
        if cached:
            return cached
        url = "https://api.glassnode.com/v1/metrics/market/mvrv_ratio"
        params = {"api_key": self.settings.glassnode_api_key, "a": asset}
        data = await self._request(url, params)
        if not data:
            return None
        latest = data[-1]
        mvrv = MVRVData(asset=asset, ratio=latest.get("v"), timestamp=datetime.fromtimestamp(latest.get("t"), tz=timezone.utc))
        self._cache_set(f"mvrv:{asset}", mvrv)
        return mvrv

    # ------------------------------------------------------------------
    async def get_sopr(self, asset: str) -> Optional[SOPRData]:
        if not self.settings.glassnode_api_key:
            logger.warning("Glassnode API key missing for SOPR data")
            return None
        cached = self._cache_get(f"sopr:{asset}")
        if cached:
            return cached
        url = "https://api.glassnode.com/v1/metrics/market/sopr"
        params = {"api_key": self.settings.glassnode_api_key, "a": asset}
        data = await self._request(url, params)
        if not data:
            return None
        latest = data[-1]
        sopr = SOPRData(asset=asset, ratio=latest.get("v"), timestamp=datetime.fromtimestamp(latest.get("t"), tz=timezone.utc))
        self._cache_set(f"sopr:{asset}", sopr)
        return sopr

    # ------------------------------------------------------------------
    async def get_reserves(self, asset: str) -> Optional[ReserveData]:
        if not self.settings.cryptoquant_api_key:
            logger.warning("CryptoQuant API key missing for reserves data")
            return None
        cached = self._cache_get(f"reserves:{asset}")
        if cached:
            return cached
        url = "https://api.cryptoquant.com/v2/main/exchange_reserve"
        params = {"apikey": self.settings.cryptoquant_api_key, "symbol": asset}
        data = await self._request(url, params)
        if not data:
            return None
        # Simplified parsing – assume payload contains "data" list
        reserves = data.get("data", [])
        if not reserves:
            return None
        latest = reserves[-1]
        reserve = ReserveData(asset=asset, amount=latest.get("amount"), timestamp=datetime.fromtimestamp(latest.get("timestamp"), tz=timezone.utc))
        self._cache_set(f"reserves:{asset}", reserve)
        return reserve

    # ------------------------------------------------------------------
    async def get_funding_rate(self, asset: str) -> Optional[FundingRateData]:
        if not self.settings.cryptoquant_api_key:
            logger.warning("CryptoQuant API key missing for funding data")
            return None
        cached = self._cache_get(f"funding:{asset}")
        if cached:
            return cached
        url = "https://api.cryptoquant.com/v2/main/funding_rate"
        params = {"apikey": self.settings.cryptoquant_api_key, "symbol": asset}
        data = await self._request(url, params)
        if not data:
            return None
        rates = data.get("data", [])
        if not rates:
            return None
        latest = rates[-1]
        fr = FundingRateData(
            asset=asset,
            rate=latest.get("rate"),
            timestamp=datetime.fromtimestamp(latest.get("timestamp"), tz=timezone.utc),
        )
        self._cache_set(f"funding:{asset}", fr)
        return fr

    # ------------------------------------------------------------------
    async def get_open_interest(self, asset: str) -> Optional[OpenInterestData]:
        if not self.settings.cryptoquant_api_key:
            logger.warning("CryptoQuant API key missing for open‑interest data")
            return None
        cached = self._cache_get(f"oi:{asset}")
        if cached:
            return cached
        url = "https://api.cryptoquant.com/v2/main/open_interest"
        params = {"apikey": self.settings.cryptoquant_api_key, "symbol": asset}
        data = await self._request(url, params)
        if not data:
            return None
        oi_series = data.get("data", [])
        if not oi_series:
            return None
        latest = oi_series[-1]
        oi = OpenInterestData(
            asset=asset,
            amount=latest.get("amount"),
            timestamp=datetime.fromtimestamp(latest.get("timestamp"), tz=timezone.utc),
        )
        self._cache_set(f"oi:{asset}", oi)
        return oi

    # ------------------------------------------------------------------
    async def close(self) -> None:
        await self._client.aclose()

# End of OnChainDataClient
