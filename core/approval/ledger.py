"""In-task approval ledger.

Approval is scoped to (service, action, proposal). Approving GA4 never
approves Meta; inspecting Merchant Center never approves modifying it;
destructive proposals need their own explicit confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.services import SERVICE_BY_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalLedger:
    approved: dict[str, list[str]] = field(default_factory=lambda: {sid: [] for sid in SERVICE_BY_ID})
    approved_proposals: list[str] = field(default_factory=list)
    destructive_confirmed: list[str] = field(default_factory=list)
    rejected_proposals: list[str] = field(default_factory=list)
    merchant_inspection: bool = False
    merchant_inspection_refused: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: str, **data: Any) -> None:
        self.history.append({"at": _now(), "event": event, **data})

    def approve(self, proposal_id: str, service: str, action: str) -> None:
        if proposal_id.startswith("M") and not self.merchant_inspection:
            raise PermissionError("merchant modification cannot be approved before merchant inspection")
        lst = self.approved.setdefault(service, [])
        if action not in lst:
            lst.append(action)
        if proposal_id not in self.approved_proposals:
            self.approved_proposals.append(proposal_id)
        if proposal_id in self.rejected_proposals:
            self.rejected_proposals.remove(proposal_id)
        self.record("approved", proposal=proposal_id, service=service, action=action)

    def confirm_destructive(self, proposal_id: str) -> None:
        if proposal_id not in self.approved_proposals:
            raise PermissionError("destructive confirmation requires prior approval of the proposal")
        if proposal_id not in self.destructive_confirmed:
            self.destructive_confirmed.append(proposal_id)
        self.record("destructive_confirmed", proposal=proposal_id)

    def reject(self, proposal_id: str) -> None:
        if proposal_id not in self.rejected_proposals:
            self.rejected_proposals.append(proposal_id)
        if proposal_id in self.approved_proposals:  # a later "no" withdraws an earlier "yes"
            self.approved_proposals.remove(proposal_id)
        if proposal_id in self.destructive_confirmed:
            self.destructive_confirmed.remove(proposal_id)
        self.record("rejected", proposal=proposal_id)

    def revoke_all(self) -> None:
        for lst in self.approved.values():
            lst.clear()
        self.approved_proposals.clear()
        self.destructive_confirmed.clear()
        self.record("revoked_all")

    def is_approved(self, proposal_id: str, service: str, action: str) -> bool:
        return proposal_id in self.approved_proposals and action in self.approved.get(service, [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "approved_proposals": self.approved_proposals,
            "destructive_confirmed": self.destructive_confirmed,
            "rejected_proposals": self.rejected_proposals,
            "merchant_inspection": self.merchant_inspection,
            "merchant_inspection_refused": self.merchant_inspection_refused,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApprovalLedger:
        led = cls()
        led.approved.update({k: list(v) for k, v in (d.get("approved") or {}).items()})
        led.approved_proposals = list(d.get("approved_proposals") or [])
        led.destructive_confirmed = list(d.get("destructive_confirmed") or [])
        led.rejected_proposals = list(d.get("rejected_proposals") or [])
        led.merchant_inspection = bool(d.get("merchant_inspection"))
        led.merchant_inspection_refused = bool(d.get("merchant_inspection_refused"))
        led.history = list(d.get("history") or [])
        return led
