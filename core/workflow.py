"""Workflow orchestrator: STORE -> DISCOVERY -> AUDIT -> REPORT -> APPROVAL ->
EXECUTION -> VERIFICATION -> RE-AUDIT -> (MERCHANT) -> FINAL.

Every public method returns ``Reply`` (Arabic text for the user + machine data
for the agent) and persists the session. Illegal steps raise
``IllegalTransition`` / ``WriteRefused`` which the CLI turns into Arabic
explanations; nothing here performs a platform write itself - writes are done
by the agent through its browser tool, only after ``authorize`` succeeded.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.approval.ledger import ApprovalLedger
from core.approval.parser import AMBIGUOUS, REJECT, parse_approval, parse_yes_no
from core.approval.proposals import ACTIONS, Proposal, build_proposals
from core.audit.engine import AuditResult, run_audit, run_merchant_inspection
from core.discovery.observation import ObservationError, sanitize_observation, validate_observation
from core.execution.change_record import ChangeRecord
from core.execution.gate import WriteRefused, WriteTarget, authorize_write
from core.invocation import InvalidStoreUrl, normalize_ar, normalize_store_url, parse_invocation
from core.logging_utils import get_logger
from core.models import ServiceStatus
from core.reporting.arabic_report import render_audit_report, render_proposals, render_verification
from core.reporting.guard import check_text
from core.reporting.messages import raw, t
from core.services import SERVICE_BY_ID, display_name
from core.session import load_session, new_session_id, save_observation, save_session
from core.state_machine import IllegalTransition, WorkflowMachine, WorkflowState
from core.verification.verifier import StaleEvidence, ensure_fresh, verify

S = WorkflowState
log = get_logger("nittaq.workflow")
INCOMPLETE_STATUSES = {
    ServiceStatus.UNABLE_TO_VERIFY,
    ServiceStatus.AUTHENTICATION_REQUIRED,
    ServiceStatus.USER_ACTION_REQUIRED,
    ServiceStatus.ERROR,
}
_CONFIRM = re.compile(r"(?<!\w)(اكد|أكد|أؤكد|اؤكد|confirm)(?!\w)\s*([PpMm]\s?\d{1,3})?")


@dataclass
class Reply:
    text: str
    state: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "state": self.state, "data": self.data}


class Workflow:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.machine = WorkflowMachine.from_dict(data["machine"])
        self.ledger = ApprovalLedger.from_dict(data.get("ledger") or {})
        self.proposals = [Proposal.from_dict(p) for p in data.get("proposals") or []]
        self.changes = [ChangeRecord.from_dict(c) for c in data.get("changes") or []]

    # ------------------------------------------------------------ persistence
    @classmethod
    def create(cls, allow_local: bool = False) -> Workflow:
        data = {
            "id": new_session_id(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "allow_local": allow_local,
            "store_url": None,
            "intent": None,
            "focus_services": [],
            "merchant_requested": False,
            "machine": WorkflowMachine().to_dict(),
            "observations": [],
            "audit": None,
            "proposals": [],
            "offer": [],
            "pending_destructive": [],
            "ledger": ApprovalLedger().to_dict(),
            "authorizations": [],
            "changes": [],
            "verification": [],
            "reaudit": None,
            "merchant": {"stage": "not_started", "audit": None, "offer": []},
            "failed_reason": None,
        }
        wf = cls(data)
        wf.save()
        return wf

    @classmethod
    def load(cls, session_id: str) -> Workflow:
        return cls(load_session(session_id))

    def save(self) -> None:
        self.data["machine"] = self.machine.to_dict()
        self.data["ledger"] = self.ledger.to_dict()
        self.data["proposals"] = [p.to_dict() for p in self.proposals]
        self.data["changes"] = [c.to_dict() for c in self.changes]
        save_session(self.data)

    @property
    def id(self) -> str:
        return str(self.data["id"])

    def _reply(self, text: str, **data: Any) -> Reply:
        self.save()
        return Reply(check_text(text), self.machine.state.value, {"session": self.id, **data})

    def _go(self, target: WorkflowState) -> None:
        self.machine.transition(target)

    # ------------------------------------------------------------ start
    def start(self, text: str) -> Reply:
        req = parse_invocation(text, allow_local=bool(self.data.get("allow_local")))
        self.data.update(intent=req.intent, focus_services=req.focus_services, merchant_requested=req.merchant_requested)
        if req.url_error:
            self._go(S.WAITING_FOR_STORE)
            return self._reply(t(f"invalid_url.{req.url_error}"), need="store_url")
        if not req.store_url:
            self._go(S.WAITING_FOR_STORE)
            key = "welcome" if req.intent == "welcome" else "need_store_url"
            return self._reply(t(key), need="store_url")
        return self._begin(req.store_url)

    def provide_store(self, text: str) -> Reply:
        if self.machine.state != S.WAITING_FOR_STORE:
            raise IllegalTransition(self.machine.state, S.DISCOVERING)
        req = parse_invocation(text if "مدقق نطاق" in text else f"مدقق نطاق {text}", allow_local=bool(self.data.get("allow_local")))
        if req.url_error:
            return self._reply(t(f"invalid_url.{req.url_error}"), need="store_url")
        if not req.store_url:
            return self._reply(t("need_store_url"), need="store_url")
        if req.focus_services:
            self.data["focus_services"] = req.focus_services
        return self._begin(req.store_url)

    def _begin(self, url: str) -> Reply:
        self.data["store_url"] = url
        self._go(S.DISCOVERING)
        return self._reply(t("audit_starting", store_url=url), need="observation", store_url=url,
                           focus_services=self.data["focus_services"])

    # ------------------------------------------------------------ discovery/audit
    def _accept_observation(self, obs: dict[str, Any], kind: str) -> dict[str, Any]:
        errs = validate_observation(obs)
        if errs:
            raise ObservationError("; ".join(errs))
        store = self.data.get("store_url")
        try:
            obs_host = normalize_store_url(obs["store_url"], allow_local=True).split("/")[2]
            store_host = normalize_store_url(store, allow_local=True).split("/")[2] if store else obs_host
        except InvalidStoreUrl as exc:
            raise ObservationError(str(exc)) from exc
        if kind != "merchant" and obs_host.removeprefix("www.") != store_host.removeprefix("www."):
            raise ObservationError(f"observation is for {obs_host}, session store is {store_host}")
        clean = sanitize_observation(obs)
        path = save_observation(self.id, kind, clean)
        self.data["observations"].append({"kind": kind, "path": path, "collected_at": clean.get("collected_at")})
        return clean

    def ingest_audit(self, obs: dict[str, Any]) -> Reply:
        if self.machine.state != S.DISCOVERING:
            raise IllegalTransition(self.machine.state, S.AUDITING)
        clean = self._accept_observation(obs, "audit")
        pages = clean.get("pages") or []
        if pages and all(p.get("status", "ok") != "ok" for p in pages):
            st = {p.get("status") for p in pages}
            if st & {"captcha", "two_factor", "user_action_required"}:
                self._go(S.USER_ACTION_REQUIRED)
                return self._reply(t("user_action.captcha", service="المتجر"), need="user_action")
            if "auth_required" in st:
                self._go(S.AUTH_REQUIRED)
                return self._reply(t("auth_required", service="المتجر"), need="user_login")
            return self.fail_safe(t("errors.page_not_loading", url=self.data["store_url"]))
        self._go(S.AUDITING)
        audit = run_audit(clean, self.data.get("focus_services") or None)
        self.data["audit"] = audit.to_dict()
        self._go(S.REPORT_READY)
        report = render_audit_report(audit)
        self.proposals = [p for p in self.proposals if p.merchant] + build_proposals(audit)
        offer = [p for p in self.proposals if not p.merchant]
        if offer:
            self._go(S.WAITING_FOR_APPROVAL)
            self.data["offer"] = [p.id for p in offer]
            return self._reply(report + "\n\n" + render_proposals(offer), need="approval", audit=audit.to_dict(),
                               offer=self.data["offer"])
        return self._to_merchant_gate(report)

    # ------------------------------------------------------------ approval
    def _offer(self) -> list[Proposal]:
        ids = set(self.data.get("offer") or [])
        return [p for p in self.proposals if p.id in ids]

    def reply(self, text: str) -> Reply:
        st = self.machine.state
        if st == S.WAITING_FOR_STORE:
            return self.provide_store(text)
        if st in (S.WAITING_FOR_APPROVAL, S.MERCHANT_WRITE_APPROVAL_REQUIRED):
            if self.data.get("pending_destructive"):
                return self._handle_destructive_confirmation(text)
            return self._handle_approval(text)
        if st == S.MERCHANT_APPROVAL_REQUIRED:
            return self._handle_merchant_inspection_answer(text)
        raise IllegalTransition(st, st)

    def _handle_approval(self, text: str) -> Reply:
        offer = self._offer()
        decision = parse_approval(text, offer)
        self.ledger.record("reply", decision=decision.kind, reason=decision.reason)
        if decision.kind == AMBIGUOUS:
            self._go(self.machine.state)  # explicit clarification loop (self-transition)
            return self._reply(t(f"approval.clarify.{decision.reason}"), need="approval", clarification=decision.reason)
        for pid in decision.rejected:
            p = self._proposal(pid)
            p.status = "rejected"
            self.ledger.reject(pid)
        for pid in decision.approved:
            p = self._proposal(pid)
            p.status = "approved"
            self.ledger.approve(pid, p.service, p.action)
        parts = []
        if decision.approved:
            parts.append(t("approval.approved", items=self._labels(decision.approved)))
        if decision.rejected:
            parts.append(t("approval.rejected", items=self._labels(decision.rejected)))
        if not decision.approved:
            parts = [t("approval.all_rejected") if len(decision.rejected) == len(offer) else parts[0]]
            merchant = self.machine.state == S.MERCHANT_WRITE_APPROVAL_REQUIRED
            self.data["offer"] = []
            if merchant:
                return self._finalize(t("merchant.write_refused"))
            return self._to_merchant_gate("\n".join(parts))
        self.data["offer"] = []
        if decision.needs_destructive_confirmation:
            self.data["pending_destructive"] = list(decision.needs_destructive_confirmation)
            first = self._proposal(decision.needs_destructive_confirmation[0])
            parts.append(t("approval.destructive_confirm", id=first.id, description=t(f"actions.{first.action}")))
            self._go(self.machine.state)
            return self._reply("\n\n".join(parts), need="destructive_confirmation", pending=self.data["pending_destructive"])
        return self._enter_execution("\n\n".join(parts))

    def _handle_destructive_confirmation(self, text: str) -> Reply:
        pending: list[str] = self.data["pending_destructive"]
        norm = normalize_ar(text)
        m = _CONFIRM.search(text) or _CONFIRM.search(norm)
        target = pending[0]
        if m and m.group(2):
            target = m.group(2).replace(" ", "").upper()
        if m and target in pending:
            self.ledger.confirm_destructive(target)
            pending.remove(target)
            msg = t("approval.destructive_confirmed", id=target)
        elif parse_yes_no(text) == REJECT:
            p = self._proposal(target)
            p.status = "rejected"
            self.ledger.reject(target)
            pending.remove(target)
            msg = t("approval.rejected", items=self._labels([target]))
        else:
            p = self._proposal(target)
            return self._reply(t("approval.destructive_confirm", id=p.id, description=t(f"actions.{p.action}")),
                               need="destructive_confirmation", pending=pending)
        if pending:
            nxt = self._proposal(pending[0])
            return self._reply(msg + "\n\n" + t("approval.destructive_confirm", id=nxt.id, description=t(f"actions.{nxt.action}")),
                               need="destructive_confirmation", pending=pending)
        approved_now = [p for p in self.proposals if p.status == "approved"]
        if not approved_now:
            if self.machine.state == S.MERCHANT_WRITE_APPROVAL_REQUIRED:
                return self._finalize(msg + "\n" + t("merchant.write_refused"))
            return self._to_merchant_gate(msg)
        return self._enter_execution(msg)

    def _enter_execution(self, prefix: str) -> Reply:
        self._go(S.EXECUTING)
        approved = [p for p in self.proposals if p.status == "approved"]
        text = prefix + "\n\n" + t("execution.started", items=self._labels([p.id for p in approved]))
        return self._reply(text, need="execute", approved=[p.to_dict() for p in approved])

    # ------------------------------------------------------------ execution
    def authorize(self, proposal_id: str, target: WriteTarget) -> Reply:
        p = self._proposal(proposal_id)
        try:
            auth = authorize_write(self.machine, self.ledger, p, target)
        except WriteRefused as exc:
            self.ledger.record("write_refused", proposal=proposal_id, code=exc.code)
            self.save()
            detail = exc.detail or ", ".join(p.expected_targets)
            raise WriteRefused(exc.code, t(f"execution.refused.{exc.code}", detail=detail)) from exc
        self.data["authorizations"].append(auth)
        label = f"{display_name(p.service)} {target.resource_id or ''}".strip()
        return self._reply(t("execution.authorized", target=label, proposal=p.id), authorization=auth)

    def record_change(self, token: str, previous_state: dict[str, Any], action_taken: str, result: str,
                      rollback: dict[str, Any] | None = None) -> Reply:
        if self.machine.state != S.EXECUTING:
            raise IllegalTransition(self.machine.state, S.EXECUTING)
        auth = next((a for a in self.data["authorizations"] if a["token"] == token), None)
        if auth is None or auth["used"]:
            raise WriteRefused("token_invalid", t("execution.refused.token_invalid"))
        p = self._proposal(auth["proposal"])
        rec = ChangeRecord(
            id=uuid.uuid4().hex[:12],
            token=token,
            proposal=p.id,
            service=p.service,
            action=p.action,
            previous_state=previous_state,
            approved_change=t(f"actions.{p.action}"),
            action_taken=action_taken,
            result=result,
            rollback=rollback or {"possible": False, "how": None},
        )
        auth["used"] = True
        self.changes.append(rec)
        p.status = "executed" if result in ("applied", "partial") else "failed"
        return self._reply(t("execution.recorded", proposal=p.id, result=raw("execution.results")[result]), change=rec.to_dict())

    def begin_verification(self) -> Reply:
        self._go(S.VERIFYING)
        not_done = [p.id for p in self.proposals if p.status == "approved"]
        text = t("verification.collect")
        if not_done:
            text += "\n" + t("verification.not_executed", items=self._labels(not_done))
        return self._reply(text, need="verification_observation", not_executed=not_done,
                           merchant=any(c.service == "merchant" for c in self.changes))

    def ingest_verification(self, obs: dict[str, Any]) -> Reply:
        if self.machine.state != S.VERIFYING:
            raise IllegalTransition(self.machine.state, S.RE_AUDITING)
        pending = [c for c in self.changes if c.verification_result == "pending"]
        merchant = any(c.service == "merchant" for c in pending)
        try:
            ensure_fresh(obs, pending)
        except StaleEvidence:
            return self._reply(t("verification.stale"), need="verification_observation")
        clean = self._accept_observation(obs, "merchant-verify" if merchant else "verify")
        self._go(S.RE_AUDITING)
        if merchant:
            before = AuditResult.from_dict(self.data["merchant"]["audit"])
            after = run_merchant_inspection(clean)
        else:
            before = AuditResult.from_dict(self.data["audit"])
            after = run_audit(clean, self.data.get("focus_services") or None)
        outcomes = verify(self.proposals, pending, before, after)
        self.data["verification"].extend(o.to_dict() for o in outcomes)
        self.data["reaudit"] = after.to_dict()
        text = render_verification(outcomes, after)
        if merchant:
            self.data["merchant"]["audit_after"] = after.to_dict()
            return self._finalize(text)
        text += "\n\n" + render_audit_report(after, "report.reaudit_title")
        return self._to_merchant_gate(text)

    # ------------------------------------------------------------ merchant
    def _to_merchant_gate(self, prefix: str) -> Reply:
        stage = self.data["merchant"]["stage"]
        if stage != "not_started":
            return self._finalize(prefix)
        self._go(S.MERCHANT_APPROVAL_REQUIRED)
        self.data["merchant"]["stage"] = "asked"
        return self._reply(prefix + "\n\n" + t("merchant.intro"), need="merchant_inspection_approval")

    def _handle_merchant_inspection_answer(self, text: str) -> Reply:
        ans = parse_yes_no(text)
        if ans == AMBIGUOUS:
            self._go(S.MERCHANT_APPROVAL_REQUIRED)
            return self._reply(t("approval.clarify.uncertain_reply"), need="merchant_inspection_approval")
        if ans == REJECT:
            self.ledger.merchant_inspection_refused = True
            self.ledger.record("merchant_inspection_refused")
            self.data["merchant"]["stage"] = "refused"
            return self._finalize(t("merchant.inspection_refused"))
        self.ledger.merchant_inspection = True
        self.ledger.record("merchant_inspection_approved")
        self.data["merchant"]["stage"] = "inspecting"
        self._go(S.MERCHANT_INSPECTING)
        return self._reply(t("merchant.inspection_approved"), need="merchant_observation")

    def ingest_merchant(self, obs: dict[str, Any]) -> Reply:
        if self.machine.state != S.MERCHANT_INSPECTING or not self.ledger.merchant_inspection:
            raise IllegalTransition(self.machine.state, S.MERCHANT_REPORT_READY)
        clean = self._accept_observation(obs, "merchant")
        audit = run_merchant_inspection(clean)
        self.data["merchant"]["audit"] = audit.to_dict()
        self.data["merchant"]["stage"] = "inspected"
        self._go(S.MERCHANT_REPORT_READY)
        report = render_audit_report(audit, "merchant.report_title")
        start = 1 + sum(1 for p in self.proposals if p.merchant)
        mprops = build_proposals(audit, merchant=True, start=start)
        if not mprops:
            return self._finalize(report)
        self.proposals.extend(mprops)
        self.data["offer"] = [p.id for p in mprops]
        self._go(S.MERCHANT_WRITE_APPROVAL_REQUIRED)
        text = report + "\n\n" + render_proposals(mprops, "merchant.write_question")
        return self._reply(text, need="merchant_write_approval", offer=self.data["offer"], audit=audit.to_dict())

    # ------------------------------------------------------------ pauses / failure / end
    def pause(self, kind: str, service: str, **params: Any) -> Reply:
        """kind: auth_required | captcha | two_factor | multiple_accounts | unexpected_ui | permission_denied | session_expired | customer_login"""
        name = display_name(service) if service in SERVICE_BY_ID else service
        if kind in ("auth_required", "session_expired"):
            self._go(S.AUTH_REQUIRED)
            key = "auth_required" if kind == "auth_required" else "user_action.session_expired"
            return self._reply(t(key, service=name), need="user_login")
        if kind not in raw("user_action"):
            raise ValueError(f"unknown pause kind: {kind}")
        self._go(S.USER_ACTION_REQUIRED)
        return self._reply(t(f"user_action.{kind}", service=name, **params), need="user_action", kind=kind)

    def resume(self) -> Reply:
        state = self.machine.resume()
        return self._reply(t("resumed"),
                           need={"DISCOVERING": "observation", "EXECUTING": "execute", "VERIFYING": "verification_observation",
                                 "MERCHANT_INSPECTING": "merchant_observation", "RE_AUDITING": "none"}.get(state.value, "none"))

    def fail_safe(self, reason: str) -> Reply:
        self.data["failed_reason"] = reason
        if self.machine.can(S.FAILED_SAFE):
            self._go(S.FAILED_SAFE)
        # Revoke outstanding (unused) write authorisations.
        for a in self.data["authorizations"]:
            a["used"] = True
        return self._reply(t("final.failed_safe", reason=reason), need="none")

    def _finalize(self, prefix: str) -> Reply:
        # PARTIALLY_COMPLETED = something approved was not executed/verified, or a
        # check could not be completed. Issues the user chose not to fix do not
        # make the audit itself partial.
        unverified = [v for v in self.data["verification"] if v["result"] != "verified"]
        snapshot = self.data["reaudit"] or self.data["audit"]
        weak = False
        if snapshot:
            audit = AuditResult.from_dict(snapshot)
            weak = any(r.status in INCOMPLETE_STATUSES for r in audit.results.values())
        never_run = [p.id for p in self.proposals if p.status == "approved"]
        target = S.PARTIALLY_COMPLETED if (unverified or weak or never_run) else S.COMPLETED
        self._go(target)
        tail = t("final.partial") if target == S.PARTIALLY_COMPLETED else t("final.completed")
        return self._reply(prefix + "\n\n" + tail, need="none", not_executed=never_run)

    # ------------------------------------------------------------ helpers
    def _proposal(self, pid: str) -> Proposal:
        for p in self.proposals:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def _labels(self, ids: list[str]) -> str:
        out = []
        for pid in ids:
            p = self._proposal(pid)
            out.append(f"{p.id} ({display_name(p.service)})")
        return "، ".join(out)

    def status(self) -> dict[str, Any]:
        return {
            "session": self.id,
            "state": self.machine.state.value,
            "store_url": self.data.get("store_url"),
            "offer": self.data.get("offer"),
            "proposals": [p.to_dict() for p in self.proposals],
            "ledger": self.ledger.to_dict(),
            "changes": [c.to_dict() for c in self.changes],
            "merchant_stage": self.data["merchant"]["stage"],
            "known_actions": len(ACTIONS),
        }
