"""Change record: what was changed, from what, with which approval, and
whether it was verified. Rollback is only described when the platform
actually allows it; it is never promised otherwise."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

RESULTS = {"applied", "failed", "partial", "not_applied"}
VERIFICATION = {"pending", "verified", "partially_verified", "failed", "unable_to_verify"}


@dataclass
class ChangeRecord:
    id: str
    token: str
    proposal: str
    service: str
    action: str
    previous_state: dict[str, Any]  # {"captured": bool, ...}; captured=False must include "reason"
    approved_change: str
    action_taken: str
    result: str
    rollback: dict[str, Any] = field(default_factory=lambda: {"possible": False, "how": None})
    verification_result: str = "pending"
    verification_detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.result not in RESULTS:
            raise ValueError(f"result must be one of {sorted(RESULTS)}")
        if self.verification_result not in VERIFICATION:
            raise ValueError(f"verification_result must be one of {sorted(VERIFICATION)}")
        if not isinstance(self.previous_state, dict) or "captured" not in self.previous_state:
            raise ValueError("previous_state must state whether it was captured")
        if not self.previous_state["captured"] and not self.previous_state.get("reason"):
            raise ValueError("previous_state not captured: a reason is required")
        if self.rollback.get("possible") and not self.rollback.get("how"):
            raise ValueError("rollback marked possible without describing how")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChangeRecord:
        return cls(**d)
