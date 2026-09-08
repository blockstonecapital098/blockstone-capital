"""
Asset universe configuration — defines which symbols to trade and monitor.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class AssetConfig:
    # Primary tradeable assets
    primary: List[str] = field(default_factory=lambda: [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
        "XRP/USDT", "ADA/USDT", "AVAX/USDT", "MATIC/USDT",
        "LINK/USDT", "DOT/USDT",
    ])
    # Watchlist (monitored but not always traded)
    watchlist: List[str] = field(default_factory=lambda: [
        "DOGE/USDT", "SHIB/USDT", "LTC/USDT", "BCH/USDT",
        "ATOM/USDT", "UNI/USDT", "AAVE/USDT", "FIL/USDT",
    ])
    # Blacklisted — never traded
    blacklist: Set[str] = field(default_factory=lambda: {
        "LUNA/USDT", "LUNA2/USDT", "FTT/USDT",
    })
    # Minimum 24h volume (USD) to qualify for trading
    min_volume_usd: float = 50_000_000.0
    # Minimum market cap (USD)
    min_market_cap_usd: float = 500_000_000.0


ASSET_CONFIG = AssetConfig()
