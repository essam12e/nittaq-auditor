"""Arabic report rendering. Every function returns guard-checked text."""

from __future__ import annotations

from typing import Any

from core.approval.proposals import Proposal
from core.audit.engine import AuditResult
from core.models import SEVERITY_ORDER, Certainty, Finding, ServiceResult, ServiceStatus
from core.reporting.guard import check_text
from core.reporting.messages import has, raw, t
from core.services import SERVICE_BY_ID, display_name, ordered
from core.verification.verifier import VerificationOutcome


def _step_ar(step: str | None) -> str:
    steps = raw("steps")
    return steps.get(step or "other", step or "")


def _join(items: list[str]) -> str:
    return "، ".join(items)


def finding_text(f: Finding) -> str:
    params: dict[str, Any] = {k: v for k, v in f.params.items()}
    params.setdefault("service", display_name(f.service) if f.service in SERVICE_BY_ID else f.service)
    params["step_ar"] = _step_ar(params.get("step"))
    for key in ("ids", "tags", "targets", "site_ids"):
        if key in params and isinstance(params[key], list):
            params[f"{key}_str"] = _join([str(x) for x in params[key]])
    for key in ("event", "count", "tracking_id", "label", "value", "pages", "transaction_id", "orders"):
        params.setdefault(key, "")
    path = f"findings.{f.code}"
    if not has(path):
        return f.code  # never crash a report on an unknown code; tests assert full coverage
    tmpl = raw(path)
    try:
        return tmpl.format(**params)
    except (KeyError, IndexError):
        return tmpl.split("{")[0].strip() or f.code


def _finding_line(n: int, f: Finding) -> str:
    sev = raw("severity")[f.severity.value]
    cert = raw("certainty")[f.certainty.value]
    line = f"{n}. [{sev} · {cert}] {finding_text(f)}"
    loc = f.params.get("fix_location")
    if loc and has(f"fix_location.{loc}"):
        line += "\n   " + t(f"fix_location.{loc}")
    return line


def _untested_line(item: str) -> str:
    if item.startswith("event:"):
        name, _, reason = item.split(":", 1)[1].partition("|")
        if reason:
            return t("untested.event_reason", name=name, reason=raw("blocked_reasons").get(reason, reason))
        return t("untested.event", name=name)
    if has(f"untested.{item}"):
        return t(f"untested.{item}")
    return t("untested.other", name=item)


def render_service(res: ServiceResult) -> str:
    lines = [display_name(res.service), t(f"status.{res.status.value}")]
    if res.ids:
        lines.append(t("report.service_ids", ids=_join(res.ids)))
    issues = sorted(res.issues, key=lambda f: SEVERITY_ORDER[f.severity])
    notes = [f for f in res.findings if not f.is_issue]
    if issues:
        lines.append(t("report.problems_header"))
        lines.extend(_finding_line(i, f) for i, f in enumerate(issues, 1))
    if notes:
        lines.append(t("report.notes_header"))
        lines.extend("• " + finding_text(f) for f in notes)
    if res.status == ServiceStatus.CONNECTED_VERIFIED or res.status == ServiceStatus.PARTIALLY_VERIFIED:
        seen = [e for e in res.events_seen]
        if seen:
            lines.append(t("report.tested_header"))
            lines.extend(t("verification.event_seen", name=n) for n in seen)
    if res.untested:
        lines.append(t("report.untested_header"))
        lines.extend("• " + _untested_line(u) for u in res.untested)
    return "\n".join(lines)


def _method_line(ctx: dict[str, Any]) -> str:
    adapter = ctx.get("adapter", "")
    if ctx.get("behavioral"):
        return t("report.method_behavioral", adapter=adapter)
    if ctx.get("javascript") or ctx.get("interaction"):
        return t("report.method_agent", adapter=adapter)
    return t("report.method_static", adapter=adapter)


def render_audit_report(audit: AuditResult, title_key: str = "report.title") -> str:
    ctx = audit.context
    merchant_only = set(audit.results) == {"merchant"}
    parts = [t(title_key), t("report.store", store_url=ctx.get("store_url", "")), _method_line(ctx)]
    if not ctx.get("behavioral") and not merchant_only:
        parts.append(t("browser.static_only_note"))
    if ctx.get("steps_completed"):
        parts.append(t("report.steps_done", steps=_join([_step_ar(s) for s in ctx["steps_completed"]])))
    blocked = ctx.get("steps_blocked") or {}
    if blocked:
        reasons = raw("blocked_reasons")
        parts.append(t("report.steps_blocked", steps=_join([f"{_step_ar(s)} ({reasons.get(r, r)})" for s, r in blocked.items()])))
    if ctx.get("store_currency"):
        parts.append(t("report.store_currency", currency=ctx["store_currency"]))
    if not merchant_only and ctx.get("is_salla") is False and ctx.get("pages_loaded"):
        parts.append(t("not_salla"))
    text = "\n".join(parts)

    blocks = [render_service(audit.results[s]) for s in ordered(list(audit.results))]
    text += "\n\n" + "\n\n".join(blocks)

    if audit.cross_platform:
        cross = [t("report.cross_header")]
        cross.extend(_finding_line(i, f) for i, f in enumerate(sorted(audit.cross_platform, key=lambda f: SEVERITY_ORDER[f.severity]), 1))
        text += "\n\n" + "\n".join(cross)

    any_issue = any(r.issues for r in audit.results.values()) or any(f.is_issue for f in audit.cross_platform)
    footer = []
    if not any_issue:
        footer.append(t("report.no_problems_scoped"))
    if "purchase" not in (ctx.get("steps_completed") or []) and "merchant" not in audit.results:
        footer.append(t("report.purchase_untested"))
    footer.append(t("report.no_changes") if "merchant" not in audit.results else t("merchant.no_changes"))
    footer.append(t("report.fact_legend"))
    text += "\n\n" + "\n".join(footer)
    return check_text(text)


def render_proposals(proposals: list[Proposal], question_key: str = "proposal.question") -> str:
    if not proposals:
        return check_text(t("proposal.none"))
    lines = [t("proposal.header")]
    for p in proposals:
        lines.append(t("proposal.item", id=p.id, service=display_name(p.service), description=t(f"actions.{p.action}")))
        if p.expected_targets:
            lines.append(t("proposal.targets", targets=_join(p.expected_targets)))
        if p.fix_location and has(f"fix_location.{p.fix_location}"):
            lines.append(t("proposal.fix_location", text=t(f"fix_location.{p.fix_location}")))
        if p.destructive:
            lines.append(t("proposal.destructive"))
    lines.append("")
    lines.append(t("proposal.nothing_changed"))
    only_connect = all(p.kind == "connect" for p in proposals)
    lines.append(t("proposal.connect_question") if only_connect and len(proposals) == 1 else t(question_key))
    return check_text("\n".join(lines))


def render_verification(outcomes: list[VerificationOutcome], after: AuditResult) -> str:
    lines = [t("verification.header"), ""]
    for o in outcomes:
        status_label = t(f"status.{o.status_after}") if has(f"status.{o.status_after}") else o.status_after
        lines.append(t(f"verification.{o.result}", service=display_name(o.service), status=status_label))
        res = after.results.get(o.service)
        if res and o.result in ("verified", "partially_verified"):
            lines.extend(t("verification.event_seen", name=n) for n in res.events_seen)
        if o.resolved:
            lines.append(t("verification.resolved", items=_join(o.resolved)))
        if o.remaining:
            lines.append(t("verification.remaining", items=_join(o.remaining)))
        if o.new_issues:
            lines.append(t("verification.new_issues", items=_join(o.new_issues)))
        if res and res.untested:
            lines.append(t("report.untested_header"))
            lines.extend("• " + _untested_line(u) for u in res.untested)
        lines.append("")
    return check_text("\n".join(lines).rstrip())


def certainty_counts(audit: AuditResult) -> dict[str, int]:
    out: dict[str, int] = {c.value: 0 for c in Certainty}
    for r in audit.results.values():
        for f in r.findings:
            out[f.certainty.value] += 1
    return out
