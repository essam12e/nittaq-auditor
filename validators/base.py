"""Shared validator machinery.

The status decision implemented in ``BaseValidator.decide_status`` is the
heart of the "existence of an ID is not proof" rule:

* markup/loader evidence only            -> DETECTED at best
* no runtime (JS + network) observation   -> never CONNECTED_VERIFIED
* hits seen but not decodable             -> CONNECTED_UNVERIFIED
* decoded hits for every completed funnel
  step, no issues, more than the homepage -> CONNECTED_VERIFIED
* otherwise                               -> PARTIALLY_VERIFIED / issues
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from core.discovery.observation import AuditContext
from core.knowledge import rule
from core.models import (
    Certainty,
    Evidence,
    EvidenceSource,
    Finding,
    PlatformEvent,
    ServiceResult,
    ServiceStatus,
    Severity,
)

ISO4217 = re.compile(r"^[A-Z]{3}$")
FUNNEL = ("home", "view_item", "add_to_cart", "view_cart", "begin_checkout", "add_payment_info", "purchase")
# Minimum funnel coverage (besides the homepage) for CONNECTED_VERIFIED.
VERIFY_MIN_STEPS = ("view_item", "add_to_cart")

DUPLICATE_CODES = {"duplicate_event", "duplicate_purchase", "duplicate_page_view", "duplicate_container", "duplicate_conversion"}
MISCONFIG_CODES = {"id_detected_no_hits", "event_wrong_step", "invalid_currency", "wrong_container"}


class BaseValidator(ABC):
    service: str = ""
    # funnel step -> accepted event names (first is the canonical/expected one)
    expected_events: dict[str, tuple[str, ...]] = {}
    # events that should only occur on the given steps
    step_bound_events: dict[str, tuple[str, ...]] = {}
    base_event_step = "home"

    def __init__(self, ctx: AuditContext):
        self.ctx = ctx
        self.findings: list[Finding] = []
        self.tested: list[str] = []
        self.untested: list[str] = []

    # ------------------------------------------------------------ helpers
    def add(
        self,
        code: str,
        severity: Severity,
        certainty: Certainty,
        evidence: Iterable[Evidence] = (),
        rule_id: str | None = None,
        action: str | None = None,
        verification: str | None = None,
        fact: bool = False,
        **params: Any,
    ) -> Finding:
        """Record a finding. ``fact=True`` marks findings that *are* the observation
        (e.g. "this hit was sent twice"), so an unconfirmed rule can't downgrade them."""
        if rule_id:
            r = rule(rule_id)  # raises UnknownRule -> programming error surfaces in tests
            if not fact and not r.confirmed and certainty == Certainty.OBSERVED and severity != Severity.INFO:
                # Unconfirmed rules can't produce confirmed violations.
                certainty = Certainty.MANUAL_CHECK if r.verification_method != "engineering_inference" else Certainty.INFERRED
        for existing in self.findings:
            if existing.code == code and existing.params == params and existing.rule_id == rule_id:
                existing.evidence.extend(evidence)  # same problem seen again: merge evidence
                return existing
        f = Finding(
            service=self.service,
            code=code,
            severity=severity,
            certainty=certainty,
            evidence=list(evidence),
            rule_id=rule_id,
            params=params,
            recommended_action=action,
            verification_method=verification,
        )
        self.findings.append(f)
        return f

    def events(self) -> list[PlatformEvent]:
        return self.ctx.events_for(self.service)

    def decoded_events(self) -> list[PlatformEvent]:
        return [e for e in self.events() if e.name != "UNPARSED"]

    def events_named(self, names: Iterable[str]) -> list[PlatformEvent]:
        wanted = set(names)
        return [e for e in self.decoded_events() if e.name in wanted]

    def dashboard(self) -> dict[str, Any]:
        return self.ctx.dashboards.get(self.service, {})

    def store_currency(self) -> str | None:
        return self.ctx.store_currency

    def check_currency(self, ev: PlatformEvent, key: str = "currency", required: bool = True, rule_id: str | None = None) -> None:
        cur = ev.params.get(key)
        if cur in (None, ""):
            if required:
                self.add(
                    "missing_currency",
                    Severity.HIGH if ev.name.lower() in ("purchase", "conversion") else Severity.MEDIUM,
                    Certainty.OBSERVED,
                    [ev.evidence(f"{ev.name} sent without {key}")],
                    rule_id=rule_id,
                    action=f"{self.service}.fix_event_parameters",
                    event=ev.name,
                )
            return
        cur_s = str(cur).strip()
        if not ISO4217.match(cur_s):
            self.add(
                "invalid_currency",
                Severity.HIGH,
                Certainty.OBSERVED,
                [ev.evidence(f"{ev.name} currency '{cur_s}' is not ISO 4217")],
                rule_id=rule_id,
                action=f"{self.service}.fix_event_parameters",
                event=ev.name,
                value=cur_s,
            )
            return
        store = self.store_currency()
        if store and cur_s != store:
            self.add(
                "currency_mismatch",
                Severity.HIGH,
                Certainty.OBSERVED,
                [
                    ev.evidence(f"{ev.name} currency {cur_s}"),
                    Evidence(EvidenceSource.HTML, f"store currency {store} ({self.ctx.store_currency_source})"),
                ],
                rule_id="ga4.currency.store_match",
                action=f"{self.service}.fix_event_parameters",
                event=ev.name,
                value=cur_s,
                store_currency=store,
            )

    # ----------------------------------------------------------- common checks
    def check_funnel_coverage(self) -> None:
        completed = set(self.ctx.steps_completed)
        for step in FUNNEL:
            names = self.expected_events.get(step)
            if not names:
                continue
            seen = self.events_named(names)
            if seen:
                # Observed hits count as tested even if the step was later blocked
                # (e.g. begin_checkout fired, then a login wall appeared).
                self.tested.append(f"event:{names[0]}")
            elif step in completed:
                if self.ctx.behavioral and self.decoded_events():
                    # The platform is live (other hits decoded) but this step produced none.
                    self.add(
                        "missing_event",
                        Severity.HIGH if step == "purchase" else Severity.MEDIUM,
                        Certainty.OBSERVED,
                        [Evidence(EvidenceSource.ADAPTER, f"step '{step}' completed; no {names[0]} hit captured", step=step)],
                        action=f"{self.service}.fix_missing_events",
                        event=names[0],
                        step=step,
                    )
                    self.tested.append(f"event:{names[0]}")
            else:
                blocked = self.ctx.steps_blocked.get(step)
                self.untested.append(f"event:{names[0]}" + (f"|{blocked}" if blocked else ""))

    def check_event_timing(self) -> None:
        for name, steps in self.step_bound_events.items():
            for ev in self.events_named([name]):
                if ev.step and ev.step not in steps and ev.step != "other":
                    self.add(
                        "event_wrong_step",
                        Severity.HIGH,
                        Certainty.OBSERVED,
                        [ev.evidence(f"{name} fired on step '{ev.step}'")],
                        action=f"{self.service}.fix_event_trigger",
                        event=name,
                        step=ev.step,
                    )

    def check_same_page_duplicates(self, key_params: tuple[str, ...] = (), names: Iterable[str] | None = None, rule_id: str | None = None) -> None:
        """Same event name + same tracking id repeated within one page load/step."""
        groups: dict[tuple[Any, ...], list[PlatformEvent]] = defaultdict(list)
        pool = self.events_named(names) if names is not None else self.decoded_events()
        for ev in pool:
            if ev.page_load_id is None and ev.step is None:
                continue
            groups[(ev.name, ev.tracking_id, ev.page_load_id, ev.step)].append(ev)
        for (name, tid, _pl, step), evs in groups.items():
            if len(evs) < 2:
                continue
            same_keys = key_params and all(
                len({str(e.params.get(k)) for e in evs}) == 1 and evs[0].params.get(k) not in (None, "") for k in key_params
            )
            self.add(
                "duplicate_purchase" if name.lower() in ("purchase", "completepayment") else "duplicate_event",
                Severity.MEDIUM if same_keys else Severity.HIGH,
                Certainty.OBSERVED,
                [e.evidence(f"{name} #{i + 1} to {tid}") for i, e in enumerate(evs)],
                rule_id=rule_id,
                action=f"{self.service}.fix_duplicate_events",
                fact=True,
                event=name,
                count=len(evs),
                tracking_id=tid,
                step=step,
                deduplicable=bool(same_keys),
            )

    # ----------------------------------------------------------- status logic
    def presence_signals(self) -> tuple[set[str], bool]:
        """(ids, runtime_loader_seen)."""
        ids = self.ctx.ids_for(self.service)
        runtime = any(ld.source == EvidenceSource.NETWORK for ld in self.ctx.loaders_for(self.service))
        return ids, runtime

    def decide_status(self) -> ServiceStatus:
        ctx = self.ctx
        ids, runtime_loader = self.presence_signals()
        events = self.events()
        decoded = self.decoded_events()
        dash = self.dashboard()
        dash_status = dash.get("status")

        pages_ok = [p for p in ctx.pages if p.get("status", "ok") == "ok"]
        if not pages_ok:
            if any(p["status"] in ("captcha", "two_factor", "user_action_required") for p in ctx.page_errors):
                return ServiceStatus.USER_ACTION_REQUIRED
            if any(p["status"] == "auth_required" for p in ctx.page_errors):
                return ServiceStatus.AUTHENTICATION_REQUIRED
            return ServiceStatus.ERROR

        if not ids and not events:
            if dash_status == "auth_required":
                return ServiceStatus.AUTHENTICATION_REQUIRED
            if ctx.behavioral:
                self.add(
                    "not_detected",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.ADAPTER, f"no {self.service} loader or hits across {len(pages_ok)} loaded page(s)")],
                    action=f"{self.service}.connect",
                    pages=len(pages_ok),
                )
                return ServiceStatus.NOT_CONNECTED
            self.add(
                "not_detected_static_only",
                Severity.INFO,
                Certainty.UNVERIFIED,
                [Evidence(EvidenceSource.ADAPTER, "only static markup was available; scripts injected at runtime cannot be seen")],
            )
            return ServiceStatus.UNABLE_TO_VERIFY

        if not events:
            if not ctx.behavioral:
                self.untested.append("runtime_behaviour")
                return ServiceStatus.DETECTED
            self.add(
                "id_detected_no_hits",
                Severity.HIGH,
                Certainty.OBSERVED,
                [Evidence(EvidenceSource.ADAPTER, f"{sorted(ids)} referenced but no hits captured")],
                action=f"{self.service}.fix_missing_events",
                ids=sorted(ids),
            )
            return ServiceStatus.MISCONFIGURED

        if not decoded:
            self.untested.append("event_payloads")
            return ServiceStatus.CONNECTED_UNVERIFIED

        issues = [f for f in self.findings if f.is_issue]
        confirmed_issues = [f for f in issues if f.certainty == Certainty.OBSERVED and f.severity != Severity.LOW]
        if any(f.code in DUPLICATE_CODES and f.severity in (Severity.HIGH, Severity.CRITICAL) for f in confirmed_issues):
            return ServiceStatus.DUPLICATE_EVENTS
        if any(f.code in MISCONFIG_CODES for f in confirmed_issues):
            return ServiceStatus.MISCONFIGURED
        if confirmed_issues:
            return ServiceStatus.CONNECTED_WITH_ISSUES
        if not ctx.behavioral:
            # Agent-reported events without network capture: not strong enough.
            return ServiceStatus.PARTIALLY_VERIFIED
        completed = set(ctx.steps_completed)
        covered = all(s in completed for s in VERIFY_MIN_STEPS)
        if any(e.parse_confidence == "best_effort" for e in decoded) and not dash.get("test_events_confirmed"):
            # Payload decoded best-effort: needs the platform's own test-events
            # view (recorded by the agent) before we call it verified.
            self.untested.append("platform_test_events_confirmation")
            return ServiceStatus.PARTIALLY_VERIFIED
        if covered and not any(f.certainty in (Certainty.MANUAL_CHECK, Certainty.INFERRED) and f.is_issue for f in self.findings):
            return ServiceStatus.CONNECTED_VERIFIED
        return ServiceStatus.PARTIALLY_VERIFIED

    # ----------------------------------------------------------- template
    @abstractmethod
    def run_checks(self) -> None:
        """Platform-specific checks; append findings via self.add()."""

    def validate(self) -> ServiceResult:
        if self.events() or self.ctx.ids_for(self.service):
            self.check_funnel_coverage()
            self.check_event_timing()
            self.run_checks()
        self.check_dashboard_state()
        status = self.decide_status()
        return ServiceResult(
            service=self.service,
            status=status,
            findings=self.findings,
            ids=sorted(self.ctx.ids_for(self.service)),
            tested=sorted(set(self.tested)),
            untested=sorted(set(self.untested)),
            events_seen=sorted({e.name for e in self.decoded_events()}),
        )

    def check_dashboard_state(self) -> None:
        dash = self.dashboard()
        st = dash.get("status")
        if not st or st == "ok":
            if not dash:
                self.untested.append("dashboard_configuration")
            return
        code = {
            "auth_required": "dashboard_auth_required",
            "permission_denied": "dashboard_permission_denied",
            "captcha": "dashboard_user_action",
            "two_factor": "dashboard_user_action",
            "unexpected_ui": "dashboard_unexpected_ui",
            "multiple_accounts": "dashboard_multiple_accounts",
        }.get(st, "dashboard_unavailable")
        self.add(code, Severity.INFO, Certainty.UNVERIFIED, [Evidence(EvidenceSource.DASHBOARD, f"dashboard status: {st}")])
        self.untested.append("dashboard_configuration")
