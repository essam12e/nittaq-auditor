"""Core data model for nittaq-auditor.

Everything that flows between discovery, validators, approval, execution,
verification and reporting is expressed with these types. They are plain
dataclasses so they serialise to JSON deterministically (session files,
reports, tests).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ServiceStatus(str, Enum):
    """Explicit integration states. Never collapse these into "connected"."""

    NOT_CONNECTED = "NOT_CONNECTED"
    DETECTED = "DETECTED"
    CONNECTED_UNVERIFIED = "CONNECTED_UNVERIFIED"
    CONNECTED_VERIFIED = "CONNECTED_VERIFIED"
    CONNECTED_WITH_ISSUES = "CONNECTED_WITH_ISSUES"
    MISCONFIGURED = "MISCONFIGURED"
    DUPLICATE_EVENTS = "DUPLICATE_EVENTS"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    UNABLE_TO_VERIFY = "UNABLE_TO_VERIFY"
    ERROR = "ERROR"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


class Certainty(str, Enum):
    """Distinguishes what was seen from what was concluded."""

    OBSERVED = "observed"  # directly seen in captured evidence
    INFERRED = "inferred"  # reasoned from evidence, not directly seen
    UNVERIFIED = "unverified"  # could not be checked in this environment
    MANUAL_CHECK = "manual_check"  # rule itself needs human confirmation


class EvidenceSource(str, Enum):
    NETWORK = "network"  # captured network request
    DATALAYER = "datalayer"  # window.dataLayer entry
    HTML = "html"  # static markup / script src
    DASHBOARD = "dashboard"  # read from an official platform dashboard
    AGENT_REPORT = "agent_report"  # recorded by the agent from its own browser tool
    ADAPTER = "adapter"  # adapter / environment condition


@dataclass
class Evidence:
    source: EvidenceSource
    description: str
    page_url: str | None = None
    step: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Evidence:
        return cls(
            source=EvidenceSource(d["source"]),
            description=d.get("description", ""),
            page_url=d.get("page_url"),
            step=d.get("step"),
            data=dict(d.get("data") or {}),
        )


@dataclass
class Finding:
    service: str
    code: str  # stable machine code, e.g. "duplicate_purchase"
    severity: Severity
    certainty: Certainty
    evidence: list[Evidence] = field(default_factory=list)
    rule_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)  # values for Arabic templates
    recommended_action: str | None = None  # action id, see core.approval.proposals
    verification_method: str | None = None

    @property
    def is_issue(self) -> bool:
        return self.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "code": self.code,
            "severity": self.severity.value,
            "certainty": self.certainty.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "rule_id": self.rule_id,
            "params": self.params,
            "recommended_action": self.recommended_action,
            "verification_method": self.verification_method,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        return cls(
            service=d["service"],
            code=d["code"],
            severity=Severity(d["severity"]),
            certainty=Certainty(d["certainty"]),
            evidence=[Evidence.from_dict(e) for e in d.get("evidence", [])],
            rule_id=d.get("rule_id"),
            params=dict(d.get("params") or {}),
            recommended_action=d.get("recommended_action"),
            verification_method=d.get("verification_method"),
        )


@dataclass
class ServiceResult:
    service: str
    status: ServiceStatus
    findings: list[Finding] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)  # e.g. measurement / pixel ids seen
    tested: list[str] = field(default_factory=list)  # checks actually performed & passed/failed
    untested: list[str] = field(default_factory=list)  # checks that could not be performed
    events_seen: list[str] = field(default_factory=list)

    @property
    def issues(self) -> list[Finding]:
        return [f for f in self.findings if f.is_issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "ids": self.ids,
            "tested": self.tested,
            "untested": self.untested,
            "events_seen": self.events_seen,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ServiceResult:
        return cls(
            service=d["service"],
            status=ServiceStatus(d["status"]),
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            ids=list(d.get("ids", [])),
            tested=list(d.get("tested", [])),
            untested=list(d.get("untested", [])),
            events_seen=list(d.get("events_seen", [])),
        )


@dataclass
class PlatformEvent:
    """A single tracking hit/event attributed to a platform."""

    platform: str  # service id: ga4, google_ads, meta, tiktok, snapchat, gtm
    name: str  # event name as sent (purchase, Purchase, PURCHASE, conversion ...)
    tracking_id: str | None  # G-..., AW-..., pixel id ...
    params: dict[str, Any] = field(default_factory=dict)
    source: EvidenceSource = EvidenceSource.NETWORK
    page_url: str | None = None
    step: str | None = None
    page_load_id: int | None = None  # index of the page load within the observation
    seq: int = 0  # order of capture within the observation
    parse_confidence: str = "high"  # "high" | "best_effort"
    raw_url: str | None = None

    def evidence(self, description: str) -> Evidence:
        data: dict[str, Any] = {
            "platform": self.platform,
            "event": self.name,
            "tracking_id": self.tracking_id,
            "params": self.params,
            "parse_confidence": self.parse_confidence,
        }
        if self.raw_url:
            data["request_url"] = self.raw_url[:500]
        return Evidence(
            source=self.source,
            description=description,
            page_url=self.page_url,
            step=self.step,
            data=data,
        )
