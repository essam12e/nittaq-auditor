"""Audit engine: runs validators in the required order over one observation.

Pure function of the observation - performs no I/O and no writes, which is
what makes the audit phase read-only by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.audit.duplicates import detect_cross_platform
from core.discovery.observation import AuditContext, build_context
from core.models import Finding, ServiceResult
from core.services import TRACKING_SERVICE_IDS, ordered
from validators import TRACKING_VALIDATORS, MerchantValidator


@dataclass
class AuditResult:
    results: dict[str, ServiceResult]
    cross_platform: list[Finding] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "cross_platform": [f.to_dict() for f in self.cross_platform],
            "context": self.context,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditResult:
        return cls(
            results={k: ServiceResult.from_dict(v) for k, v in d.get("results", {}).items()},
            cross_platform=[Finding.from_dict(f) for f in d.get("cross_platform", [])],
            context=dict(d.get("context") or {}),
            created_at=d.get("created_at", ""),
        )


def summarize_context(ctx: AuditContext) -> dict[str, Any]:
    return {
        "store_url": ctx.store_url,
        "adapter": ctx.adapter,
        "behavioral": ctx.behavioral,
        "javascript": ctx.javascript,
        "network_capture": ctx.network_capture,
        "interaction": ctx.interaction,
        "is_salla": ctx.is_salla,
        "salla_reasons": ctx.salla_reasons,
        "store_currency": ctx.store_currency,
        "store_currency_source": ctx.store_currency_source,
        "steps_completed": ctx.steps_completed,
        "steps_blocked": ctx.steps_blocked,
        "pages_loaded": sum(1 for p in ctx.pages if p.get("status", "ok") == "ok"),
        "page_errors": ctx.page_errors,
        "events_captured": len(ctx.events),
    }


def run_audit(observation: dict[str, Any], services: list[str] | None = None) -> AuditResult:
    ctx = build_context(observation)
    wanted = ordered(services) if services else list(TRACKING_SERVICE_IDS)
    results: dict[str, ServiceResult] = {}
    for sid in wanted:
        if sid not in TRACKING_VALIDATORS:
            continue  # merchant is never part of the tracking audit
        results[sid] = TRACKING_VALIDATORS[sid](ctx).validate()
    return AuditResult(results=results, cross_platform=detect_cross_platform(ctx), context=summarize_context(ctx))


def run_merchant_inspection(observation: dict[str, Any]) -> AuditResult:
    ctx = build_context(observation)
    return AuditResult(results={"merchant": MerchantValidator(ctx).validate()}, context=summarize_context(ctx))
