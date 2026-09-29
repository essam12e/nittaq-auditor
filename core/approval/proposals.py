"""Proposals: concrete, scoped changes offered to the user after diagnosis.

A proposal never executes anything. It describes exactly what would change,
on which service and target, its risk, and which findings it addresses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.audit.engine import AuditResult
from core.models import SEVERITY_ORDER, Finding, ServiceStatus, Severity
from core.services import SERVICE_BY_ID


@dataclass(frozen=True)
class ActionSpec:
    id: str
    service: str
    kind: str  # connect | repair | configure | publish | remove
    destructive: bool = False  # deletes/replaces/unlinks something -> extra confirmation
    reversible: str = "platform_dependent"  # "yes" | "no" | "platform_dependent"


def _a(id: str, kind: str, destructive: bool = False, reversible: str = "platform_dependent") -> ActionSpec:
    return ActionSpec(id, id.split(".", 1)[0], kind, destructive, reversible)


ACTIONS: dict[str, ActionSpec] = {
    a.id: a
    for a in (
        _a("ga4.connect", "connect"),
        _a("ga4.fix_event_parameters", "repair"),
        _a("ga4.fix_missing_events", "repair"),
        _a("ga4.fix_event_trigger", "repair"),
        _a("ga4.fix_duplicate_events", "remove", destructive=True),
        _a("gtm.connect", "connect"),
        _a("gtm.fix_container_installation", "repair"),
        _a("gtm.remove_duplicate_container", "remove", destructive=True),
        _a("gtm.confirm_container", "configure"),
        _a("gtm.review_and_publish", "publish"),
        _a("gtm.fix_duplicate_tags", "remove", destructive=True),
        _a("gtm.fix_trigger", "repair"),
        _a("gtm.fix_missing_events", "repair"),
        _a("google_ads.connect", "connect"),
        _a("google_ads.configure_purchase_conversion", "configure"),
        _a("google_ads.fix_conversion_parameters", "repair"),
        _a("google_ads.fix_duplicate_conversion", "remove", destructive=True),
        _a("google_ads.fix_conflicting_implementation", "remove", destructive=True),
        _a("google_ads.fix_missing_events", "repair"),
        _a("google_ads.fix_event_parameters", "repair"),
        _a("google_ads.fix_event_trigger", "repair"),
        _a("meta.connect", "connect"),
        _a("meta.fix_event_parameters", "repair"),
        _a("meta.fix_missing_events", "repair"),
        _a("meta.fix_event_trigger", "repair"),
        _a("meta.fix_duplicate_events", "remove", destructive=True),
        _a("meta.configure_deduplication", "configure"),
        _a("tiktok.connect", "connect"),
        _a("tiktok.fix_event_parameters", "repair"),
        _a("tiktok.fix_missing_events", "repair"),
        _a("tiktok.fix_event_trigger", "repair"),
        _a("tiktok.fix_event_names", "repair"),
        _a("tiktok.fix_duplicate_events", "remove", destructive=True),
        _a("snapchat.connect", "connect"),
        _a("snapchat.fix_event_parameters", "repair"),
        _a("snapchat.fix_missing_events", "repair"),
        _a("snapchat.fix_event_trigger", "repair"),
        _a("snapchat.fix_duplicate_events", "remove", destructive=True),
        _a("merchant.connect", "connect"),
        _a("merchant.fix_website_settings", "configure", destructive=True),
        _a("merchant.review_account_issue", "configure"),
        _a("merchant.review_data_source", "configure"),
        _a("merchant.fix_price_mismatch", "repair"),
        _a("merchant.fix_availability_mismatch", "repair"),
        _a("merchant.fix_landing_page", "repair"),
        _a("merchant.fix_identifiers", "repair"),
        _a("merchant.fix_shipping", "configure"),
        _a("merchant.fix_policy", "configure"),
        _a("merchant.fix_other", "configure"),
    )
}


@dataclass
class Proposal:
    id: str  # "P1", "P2", ... (merchant: "M1", ...)
    action: str
    service: str
    kind: str
    destructive: bool
    merchant: bool
    finding_codes: list[str]
    severity: str
    expected_targets: list[str] = field(default_factory=list)  # ids the change must apply to
    fix_location: str | None = None  # merchant: where the fix really belongs
    status: str = "proposed"  # proposed | approved | rejected | executed | verified | failed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Proposal:
        return cls(**d)


def _worst(findings: list[Finding]) -> Severity:
    return min((f.severity for f in findings), key=lambda s: SEVERITY_ORDER[s])


def build_proposals(audit: AuditResult, merchant: bool = False, start: int = 1) -> list[Proposal]:
    """One proposal per recommended action, ordered by service order then severity."""
    grouped: dict[str, list[Finding]] = {}
    for sid, res in audit.results.items():
        if SERVICE_BY_ID[sid].sensitive != merchant:
            continue
        if res.status in (ServiceStatus.AUTHENTICATION_REQUIRED, ServiceStatus.USER_ACTION_REQUIRED, ServiceStatus.ERROR):
            continue  # can't propose changes to something we could not inspect
        for f in res.findings:
            if not f.recommended_action or not f.is_issue or f.recommended_action not in ACTIONS:
                continue
            if f.code == "not_detected" and f.severity == Severity.INFO:
                continue  # optional service (e.g. GTM) - not proposed unless asked
            grouped.setdefault(f.recommended_action, []).append(f)
    if not merchant:
        for f in audit.cross_platform:
            if f.recommended_action in ACTIONS and f.is_issue:
                grouped.setdefault(f.recommended_action, []).append(f)

    def sort_key(item: tuple[str, list[Finding]]) -> tuple[int, int]:
        spec = ACTIONS[item[0]]
        return (SERVICE_BY_ID[spec.service].order, SEVERITY_ORDER[_worst(item[1])])

    prefix = "M" if merchant else "P"
    proposals = []
    for n, (action, findings) in enumerate(sorted(grouped.items(), key=sort_key), start=start):
        spec = ACTIONS[action]
        svc_result = audit.results.get(spec.service)
        targets = sorted(set(svc_result.ids)) if svc_result is not None else []
        locs = {str(f.params["fix_location"]) for f in findings if f.params.get("fix_location")}
        proposals.append(
            Proposal(
                id=f"{prefix}{n}",
                action=action,
                service=spec.service,
                kind=spec.kind,
                destructive=spec.destructive,
                merchant=merchant,
                finding_codes=sorted({f.code for f in findings}),
                severity=_worst(findings).value,
                expected_targets=targets,
                fix_location=sorted(locs)[0] if len(locs) == 1 else ("multiple" if locs else None),
            )
        )
    return proposals
