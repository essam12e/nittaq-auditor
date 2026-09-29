"""Post-change verification.

"Configuration saved" is never "integration verified". A change is only
marked verified when a *fresh* observation (collected after the change)
shows the service CONNECTED_VERIFIED and the targeted findings gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.approval.proposals import Proposal
from core.audit.engine import AuditResult
from core.execution.change_record import ChangeRecord
from core.models import ServiceStatus

UNABLE = {
    ServiceStatus.UNABLE_TO_VERIFY,
    ServiceStatus.DETECTED,
    ServiceStatus.CONNECTED_UNVERIFIED,
    ServiceStatus.AUTHENTICATION_REQUIRED,
    ServiceStatus.USER_ACTION_REQUIRED,
    ServiceStatus.ERROR,
}


class StaleEvidence(ValueError):
    pass


@dataclass
class VerificationOutcome:
    proposal: str
    service: str
    result: str  # verified | partially_verified | failed | unable_to_verify
    status_before: str | None
    status_after: str
    resolved: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    new_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def ensure_fresh(observation: dict[str, Any], changes: list[ChangeRecord]) -> None:
    collected = observation.get("collected_at")
    if not collected:
        raise StaleEvidence("verification observation has no collected_at")
    if changes:
        last = max(_parse_ts(c.timestamp) for c in changes)
        if _parse_ts(str(collected)) <= last:
            raise StaleEvidence("verification observation was collected before the last change")


def verify(
    proposals: list[Proposal],
    changes: list[ChangeRecord],
    before: AuditResult,
    after: AuditResult,
) -> list[VerificationOutcome]:
    outcomes = []
    for c in changes:
        prop = next((p for p in proposals if p.id == c.proposal), None)
        if prop is None:
            continue
        res_after = after.results.get(c.service)
        res_before = before.results.get(c.service)
        if res_after is None:
            outcomes.append(VerificationOutcome(c.proposal, c.service, "unable_to_verify", None, "NOT_AUDITED"))
            c.verification_result = "unable_to_verify"
            continue
        after_codes = {f.code for f in res_after.findings if f.is_issue}
        before_codes = {f.code for f in res_before.findings if f.is_issue} if res_before else set()
        targeted = set(prop.finding_codes)
        remaining = sorted(targeted & after_codes)
        resolved = sorted(targeted - after_codes)
        new = sorted(after_codes - before_codes)
        if c.result in ("failed", "not_applied"):
            result = "failed"
        elif res_after.status in UNABLE:
            result = "unable_to_verify"
        elif remaining or new:
            result = "failed"
        elif res_after.status == ServiceStatus.CONNECTED_VERIFIED:
            result = "verified"
        else:
            result = "partially_verified"
        c.verification_result = result
        c.verification_detail = {"status_after": res_after.status.value, "remaining": remaining, "new_issues": new}
        prop.status = {"verified": "verified", "failed": "failed"}.get(result, "executed")
        outcomes.append(
            VerificationOutcome(
                c.proposal,
                c.service,
                result,
                res_before.status.value if res_before else None,
                res_after.status.value,
                resolved,
                remaining,
                new,
            )
        )
    return outcomes
