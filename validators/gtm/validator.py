"""Google Tag Manager validator (rules: gtm.*).

GTM itself sends no measurement hits, so "working" is judged from:
the container script loading at runtime, the container executing
(``gtm.js`` / ``gtm.load`` entries in dataLayer), and - when the agent could
read the GTM dashboard - its tags/triggers/publish state.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.models import Certainty, Evidence, EvidenceSource, ServiceStatus, Severity
from validators.base import BaseValidator

CONVERSION_KEYWORDS = ("purchase", "conversion", "completepayment", "order", "شراء")
ALL_PAGES_TRIGGERS = ("all pages", "all_pages", "page view - all pages", "جميع الصفحات", "كل الصفحات", "initialization - all pages")


def _tag_key(tag: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(tag.get("type", "")).lower(),
        str(tag.get("tracking_id") or tag.get("measurement_id") or tag.get("send_to") or tag.get("pixel_id") or ""),
        str(tag.get("event_name") or "").lower(),
    )


class GTMValidator(BaseValidator):
    service = "gtm"

    def run_checks(self) -> None:
        self._check_container_loads()
        self._check_datalayer()
        self._check_dashboard()

    def _check_container_loads(self) -> None:
        per_load: dict[tuple[str | None, int | None], int] = defaultdict(int)
        for ld in self.ctx.loaders_for("gtm"):
            if ld.source == EvidenceSource.NETWORK:
                per_load[(ld.tracking_id, ld.page_load_id)] += 1
        for (cid, pl), n in per_load.items():
            if n > 1:
                self.add(
                    "duplicate_container",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.NETWORK, f"{cid} gtm.js requested {n} times in one page load", data={"page_load_id": pl})],
                    rule_id="gtm.container.duplicate",
                    action="gtm.remove_duplicate_container",
                    fact=True,
                    tracking_id=cid,
                    count=n,
                )
                break
        ids = sorted({cid for cid, _ in per_load if cid} | self.ctx.html_ids.get("gtm", set()))
        if len(ids) > 1:
            self.add(
                "multiple_containers",
                Severity.LOW,
                Certainty.INFERRED,
                [Evidence(EvidenceSource.NETWORK, f"containers on the storefront: {ids}")],
                ids=ids,
            )
        if per_load:
            self.tested.append("container_loads")

    def _container_executed(self) -> bool:
        return any(d["entry"].get("event") in ("gtm.js", "gtm.dom", "gtm.load") for d in self.ctx.datalayer_events())

    def _check_datalayer(self) -> None:
        if not self.ctx.behavioral:
            return
        if self._container_executed():
            self.tested.append("container_executes")
        elif self.ctx.datalayer or any(p.get("datalayer_read") for p in self.ctx.pages):
            self.add(
                "container_not_executed",
                Severity.HIGH,
                Certainty.OBSERVED,
                [Evidence(EvidenceSource.DATALAYER, "dataLayer read but no gtm.js/gtm.load entries")],
                action="gtm.fix_container_installation",
            )
        else:
            self.untested.append("container_executes")
        ecommerce = [d for d in self.ctx.datalayer_events() if isinstance(d["entry"].get("ecommerce"), dict)]
        funnel_done = {"view_item", "add_to_cart"} & set(self.ctx.steps_completed)
        if funnel_done and not ecommerce and self.ctx.datalayer:
            self.add(
                "no_ecommerce_datalayer",
                Severity.LOW,
                Certainty.INFERRED,
                [Evidence(EvidenceSource.DATALAYER, f"steps {sorted(funnel_done)} completed; no dataLayer ecommerce objects")],
                steps=sorted(funnel_done),
            )
        elif ecommerce:
            self.tested.append("ecommerce_datalayer")

    def _check_dashboard(self) -> None:
        dash = self.dashboard()
        if dash.get("status") != "ok":
            return
        self.tested.append("dashboard_configuration")
        site_ids = self.ctx.ids_for("gtm")
        cid = dash.get("container_id")
        if cid and site_ids and cid.upper() not in site_ids:
            self.add(
                "wrong_container",
                Severity.HIGH,
                Certainty.OBSERVED,
                [Evidence(EvidenceSource.DASHBOARD, f"dashboard container {cid}; storefront loads {sorted(site_ids)}")],
                action="gtm.confirm_container",
                container=cid,
                site_ids=sorted(site_ids),
            )
        pending = dash.get("workspace_changes")
        if isinstance(pending, int) and pending > 0:
            self.add(
                "unpublished_changes",
                Severity.MEDIUM,
                Certainty.OBSERVED,
                [Evidence(EvidenceSource.DASHBOARD, f"{pending} unpublished workspace change(s)")],
                rule_id="gtm.publish.is_write",
                action="gtm.review_and_publish",
                count=pending,
            )
        tags = [t for t in dash.get("tags") or [] if isinstance(t, dict) and not t.get("paused")]
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for t in tags:
            key = _tag_key(t)
            if key[1] or key[2]:
                groups[key].append(t)
        for key, ts in groups.items():
            if len(ts) > 1:
                self.add(
                    "duplicate_tags",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.DASHBOARD, f"tags {[t.get('name') for t in ts]} send the same {key}")],
                    action="gtm.fix_duplicate_tags",
                    tags=[t.get("name") for t in ts],
                )
        for t in tags:
            name = f"{t.get('name', '')} {t.get('event_name', '')}".lower()
            triggers = [str(x).lower() for x in t.get("firing_triggers") or []]
            if any(k in name for k in CONVERSION_KEYWORDS) and any(tr in ALL_PAGES_TRIGGERS for tr in triggers):
                self.add(
                    "incorrect_trigger",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.DASHBOARD, f"conversion tag '{t.get('name')}' fires on {t.get('firing_triggers')}")],
                    action="gtm.fix_trigger",
                    tag=t.get("name"),
                )

    def decide_status(self) -> ServiceStatus:
        ctx = self.ctx
        ids, runtime = self.presence_signals()
        pages_ok = [p for p in ctx.pages if p.get("status", "ok") == "ok"]
        if not pages_ok:
            return super().decide_status()
        if not ids:
            if ctx.behavioral:
                self.add(
                    "not_detected",
                    Severity.INFO,  # GTM is optional: its absence alone is not a defect
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.ADAPTER, "no GTM container loaded")],
                    action="gtm.connect",
                    pages=len(pages_ok),
                )
                return ServiceStatus.NOT_CONNECTED
            self.add("not_detected_static_only", Severity.INFO, Certainty.UNVERIFIED)
            return ServiceStatus.UNABLE_TO_VERIFY
        if not ctx.behavioral:
            self.untested.append("runtime_behaviour")
            return ServiceStatus.DETECTED
        if not runtime:
            self.add(
                "id_detected_no_hits",
                Severity.HIGH,
                Certainty.OBSERVED,
                [Evidence(EvidenceSource.ADAPTER, f"{sorted(ids)} referenced but gtm.js was never requested")],
                action="gtm.fix_container_installation",
                ids=sorted(ids),
            )
            return ServiceStatus.MISCONFIGURED
        confirmed = [f for f in self.findings if f.is_issue and f.certainty == Certainty.OBSERVED and f.severity != Severity.LOW]
        codes = {f.code for f in confirmed}
        if codes & {"duplicate_container", "duplicate_tags"}:
            return ServiceStatus.DUPLICATE_EVENTS
        if codes & {"wrong_container", "container_not_executed", "incorrect_trigger"}:
            return ServiceStatus.MISCONFIGURED
        if confirmed:
            return ServiceStatus.CONNECTED_WITH_ISSUES
        if self._container_executed() and "dashboard_configuration" in self.tested:
            return ServiceStatus.CONNECTED_VERIFIED
        if self.dashboard().get("status") == "auth_required":
            return ServiceStatus.AUTHENTICATION_REQUIRED if not self._container_executed() else ServiceStatus.PARTIALLY_VERIFIED
        return ServiceStatus.PARTIALLY_VERIFIED
