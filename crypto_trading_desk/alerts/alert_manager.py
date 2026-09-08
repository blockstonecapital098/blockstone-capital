"""
AlertManager dispatches alerts to one or more channels (console, Telegram, Discord, email).

The active channels are determined by ``Settings.alert_channel``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import List

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertManager:
    """Dispatches formatted alert messages to configured channels.

    Supported channels (V1):
    - ``console``  – logs to Python logging (always active for debug)
    - ``telegram`` – sends via Bot API (requires env vars)
    - ``discord``  – sends via Webhook URL (requires env var)
    """

    def __init__(self, channels: List[str] | None = None):
        self.channels = [c.lower() for c in (channels or ["console"])]
        self._telegram_token: str | None = None
        self._telegram_chat_id: str | None = None
        self._discord_webhook: str | None = None
        logger.info("AlertManager initialised with channels: %s", self.channels)

    def configure_telegram(self, token: str, chat_id: str) -> None:
        self._telegram_token = token
        self._telegram_chat_id = chat_id

    def configure_discord(self, webhook_url: str) -> None:
        self._discord_webhook = webhook_url

    async def send(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO) -> None:
        formatted = f"[{level.value}] {title}\n{message}"
        for channel in self.channels:
            if channel == "console":
                if level == AlertLevel.CRITICAL:
                    logger.critical(formatted)
                elif level == AlertLevel.WARNING:
                    logger.warning(formatted)
                else:
                    logger.info(formatted)
            elif channel == "telegram":
                await self._send_telegram(formatted)
            elif channel == "discord":
                await self._send_discord(formatted)

    async def _send_telegram(self, text: str) -> None:
        if not (self._telegram_token and self._telegram_chat_id):
            logger.warning("AlertManager: Telegram not configured")
            return
        try:
            import httpx
            url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": self._telegram_chat_id, "text": text})
        except Exception as exc:
            logger.error("AlertManager: Telegram send failed: %s", exc)

    async def _send_discord(self, text: str) -> None:
        if not self._discord_webhook:
            logger.warning("AlertManager: Discord not configured")
            return
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(self._discord_webhook, json={"content": text})
        except Exception as exc:
            logger.error("AlertManager: Discord send failed: %s", exc)
