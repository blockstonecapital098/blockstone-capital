"""
Application settings loaded from environment variables using Pydantic BaseSettings.
"""
from __future__ import annotations

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Trading mode
    trading_mode: Literal["paper", "live"] = "paper"
    initial_equity: float = 1_000.0

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./trading.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Alerts
    alert_channel: str = "console"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook: str = ""

    # Data APIs
    glassnode_api_key: str = ""
    cryptoquant_api_key: str = ""
    cryptopanic_api_key: str = ""

    # LLM
    openai_api_key: str = ""

    # Logging
    log_level: str = "INFO"
