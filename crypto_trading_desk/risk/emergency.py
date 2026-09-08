"""
EmergencyManager provides a global kill‑switch that can be activated manually or by a critical failure.
When activated, all further trade proposals are rejected.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EmergencyManager:
    """Simple kill‑switch manager.

    The manager holds a single boolean flag. Once ``activate`` is called, any
    component can query ``is_active`` to abort trading. Deactivation is allowed
    only during paper‑trading mode for safety.
    """

    def __init__(self):
        self._active = False

    def activate(self, reason: str | None = None) -> None:
        self._active = True
        logger.warning("EmergencyManager activated%s", f": {reason}" if reason else "")

    def deactivate(self) -> None:
        # Typically only allowed in non‑live mode; we leave the check to the caller.
        self._active = False
        logger.info("EmergencyManager deactivated")

    @property
    def is_active(self) -> bool:
        return self._active

# End of EmergencyManager
