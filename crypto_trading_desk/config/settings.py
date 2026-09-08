"""
Application settings loaded from environment variables using Pydantic BaseSettings.
Robust against empty strings and missing cloud environment variables.
"""
from __future__ import annotations

from typing import Literal, Any
from pydantic import field_validator
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

    @field_validator("trading_mode", mode="before")
    @classmethod
    def validate_trading_mode(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "paper"
        val = str(v).strip().lower()
        return val if val in ("paper", "live") else "paper"

    @field_validator("binance_testnet", mode="before")
    @classmethod
    def validate_binance_testnet(cls, v: Any) -> bool:
        if v is None or not str(v).strip():
            return True
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "t")
        return bool(v)

    @field_validator("initial_equity", mode="before")
    @classmethod
    def validate_initial_equity(cls, v: Any) -> float:
        if v is None or not str(v).strip():
            return 1000.0
        try:
            return float(v)
        except Exception:
            return 1000.0
