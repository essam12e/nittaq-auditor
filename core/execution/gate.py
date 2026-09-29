"""Write-operation gate.

Every platform/store write performed by the agent must first obtain an
authorisation from ``authorize_write``. The gate refuses unless ALL hold:

1. the workflow is in EXECUTING (never during audit/report/approval states);
2. the exact proposal+service+action is in the approval ledger;
3. Merchant proposals were approved in the separate Merchant write step;
4. destructive proposals received their own explicit confirmation;
5. the browser is on the expected official platform host (page assertion);
6. the target account/property/container/pixel matches the audited IDs, or
   the user explicitly confirmed a new target (wrong-account protection).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from core.approval.ledger import ApprovalLedger
from core.approval.proposals import Proposal
from core.state_machine import WorkflowMachine

# Official hosts on which a write for each service may be performed.
PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "ga4": ("analytics.google.com",),
    "gtm": ("tagmanager.google.com",),
    "google_ads": ("ads.google.com",),
    "meta": ("business.facebook.com", "www.facebook.com", "adsmanager.facebook.com"),
    "tiktok": ("ads.tiktok.com", "business.tiktok.com"),
    "snapchat": ("ads.snapchat.com", "business.snapchat.com"),
    "merchant": ("merchants.google.com",),
    "salla": ("s.salla.sa", "salla.sa", "apps.salla.sa"),
}


class WriteRefused(PermissionError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class WriteTarget:
    page_url: str  # where the browser currently is (asserted by the agent from the live page)
    account_label: str | None = None  # account/store name visible on the page
    resource_id: str | None = None  # property / container / pixel / merchant id being edited
    via: str | None = None  # which dashboard performs the write: service id or "salla"
    user_confirmed_target: bool = False  # user explicitly confirmed this target in chat

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _host_ok(page_url: str, service: str) -> bool:
    host = (urlsplit(page_url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PLATFORM_HOSTS.get(service, ()))


def authorize_write(
    machine: WorkflowMachine,
    ledger: ApprovalLedger,
    proposal: Proposal,
    target: WriteTarget,
) -> dict[str, Any]:
    if not machine.allows_write:
        raise WriteRefused("not_in_execution_state", machine.state.value)
    if proposal.status == "rejected" or proposal.id in ledger.rejected_proposals:
        raise WriteRefused("proposal_rejected", proposal.id)
    if not ledger.is_approved(proposal.id, proposal.service, proposal.action):
        raise WriteRefused("not_approved", f"{proposal.id} {proposal.service}:{proposal.action}")
    if proposal.merchant and not ledger.merchant_inspection:
        raise WriteRefused("merchant_inspection_not_approved")
    if proposal.destructive and proposal.id not in ledger.destructive_confirmed:
        raise WriteRefused("destructive_not_confirmed", proposal.id)
    via = target.via or proposal.service
    if via not in (proposal.service, "salla"):
        raise WriteRefused("write_via_unrelated_service", via)
    if not _host_ok(target.page_url, via):
        raise WriteRefused("unexpected_page", target.page_url)
    if proposal.expected_targets:
        rid = (target.resource_id or "").upper()
        if not rid:
            raise WriteRefused("target_not_identified")
        expected = {t.upper() for t in proposal.expected_targets}
        if rid not in expected and not target.user_confirmed_target:
            raise WriteRefused("wrong_target", str(target.resource_id))
    elif not target.user_confirmed_target:
        # New connection: nothing audited to compare against -> the user must pick.
        raise WriteRefused("target_needs_user_confirmation")
    token = uuid.uuid4().hex
    return {
        "token": token,
        "proposal": proposal.id,
        "service": proposal.service,
        "action": proposal.action,
        "target": target.to_dict(),
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "used": False,
    }
