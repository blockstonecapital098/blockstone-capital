"""
ApprovalManager handles human approval for high-risk actions (large notional sizes, leverage escalations).
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Manages pending human approval requests for trades exceeding automatic risk thresholds."""

    def __init__(self, human_approval_threshold_notional: float = 25_000.0):
        self.threshold_notional = human_approval_threshold_notional
        self._pending_approvals: Dict[str, Any] = {}

    def requires_approval(self, proposal: Any) -> bool:
        notional = getattr(proposal, "notional", 0.0)
        leverage = getattr(proposal, "leverage", 1)
        return notional >= self.threshold_notional or leverage > 2

    def submit_for_approval(self, proposal: Any) -> str:
        prop_id = getattr(proposal, "proposal_id", "req-1")
        self._pending_approvals[prop_id] = {
            "proposal": proposal,
            "status": "PENDING_HUMAN_APPROVAL",
        }
        logger.warning("TradeProposal %s placed in pending human approval queue.", prop_id)
        return prop_id

    def approve_trade(self, proposal_id: str) -> Optional[Any]:
        item = self._pending_approvals.pop(proposal_id, None)
        if item:
            logger.info("TradeProposal %s APPROVED by human operator.", proposal_id)
            return item["proposal"]
        return None

    def reject_trade(self, proposal_id: str, reason: str = "Rejected by operator") -> bool:
        if proposal_id in self._pending_approvals:
            self._pending_approvals.pop(proposal_id)
            logger.info("TradeProposal %s REJECTED by human operator (%s).", proposal_id, reason)
            return True
        return False
