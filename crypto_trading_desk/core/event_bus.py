"""
Async EventBus — publish/subscribe for all system events.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Type

logger = logging.getLogger(__name__)


class EventBus:
    """Simple async pub/sub event bus.

    Handlers are registered per event type. When an event is published, all
    handlers for that type are awaited concurrently using ``asyncio.gather``.
    """

    def __init__(self):
        self._handlers: Dict[Type, List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable) -> None:
        self._handlers[event_type].append(handler)
        logger.debug("EventBus: subscribed %s to %s", handler, event_type.__name__)

    async def publish(self, event: Any) -> None:
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            logger.debug("EventBus: no handlers for %s", type(event).__name__)
            return
        results = await asyncio.gather(
            *[h(event) for h in handlers], return_exceptions=True
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("EventBus handler error: %s", result)
