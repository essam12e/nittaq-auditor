"""Google Ads conversion tracking validator (rules: ads.*).

A conversion action existing in the Google Ads UI is never treated as proof:
only an observed conversion request (label/value/currency/oid) is.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.models import Certainty, Evidence, EvidenceSource, PlatformEvent, ServiceStatus, Severity
from validators.base import BaseValidator


class GoogleAdsValidator(BaseValidator):
    service = "google_ads"
    expected_events = {"purchase": ("conversion",)}
    step_bound_events = {"conversion": ("purchase",)}

    def conversions(self) -> list[PlatformEvent]:
        """Logical conversions: the paired viewthrough/1p-conversion requests of
        one gtag conversion are collapsed into one."""
        seen: dict[tuple[Any, ...], PlatformEvent] = {}
        counts: dict[tuple[Any, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for ev in self.events_named(["conversion"]):
            key = (ev.tracking_id, ev.params.get("label"), ev.page_load_id, ev.params.get("transaction_id"), ev.params.get("value"))
            counts[key][ev.params.get("endpoint", "")] += 1
            seen.setdefault(key, ev)
        self._endpoint_counts = counts
        return list(seen.values())

    def run_checks(self) -> None:
        convs = self.conversions()
        for key, per_endpoint in self._endpoint_counts.items():
            n = max(per_endpoint.values())
            if n > 1:
                ev = next(e for e in convs if (e.tracking_id, e.params.get("label"), e.page_load_id, e.params.get("transaction_id"), e.params.get("value")) == key)
                self.add(
                    "duplicate_conversion",
                    Severity.MEDIUM if ev.params.get("transaction_id") else Severity.HIGH,
                    Certainty.OBSERVED,
                    [ev.evidence(f"conversion {ev.tracking_id}/{ev.params.get('label')} sent {n} times in one page load")],
                    action="google_ads.fix_duplicate_conversion",
                    count=n,
                    label=ev.params.get("label"),
                    deduplicable=bool(ev.params.get("transaction_id")),
                )
        per_load: dict[Any, set[tuple[Any, Any]]] = defaultdict(set)
        for ev in convs:
            per_load[ev.page_load_id].add((ev.tracking_id, ev.params.get("label")))
            self._check_conversion(ev)
        for targets in per_load.values():
            if len(targets) > 1:
                self.add(
                    "conflicting_implementation",
                    Severity.HIGH,
                    Certainty.INFERRED,
                    [Evidence(EvidenceSource.NETWORK, f"one page load sent conversions to {sorted(map(str, targets))}")],
                    action="google_ads.fix_conflicting_implementation",
                    targets=sorted(f"{a}/{b}" for a, b in targets),
                )
        self._check_static_value(convs)
        if convs and not any(e.params.get("user_data_present") for e in convs):
            self.add(
                "enhanced_conversions_not_observed",
                Severity.INFO,
                Certainty.UNVERIFIED,
                [Evidence(EvidenceSource.NETWORK, "no user-provided data indicator on conversion requests")],
                rule_id="ads.enhanced_conversions",
            )
        self._check_dashboard()

    def _check_conversion(self, ev: PlatformEvent) -> None:
        p = ev.params
        self.tested.append("params:conversion")
        if "value" not in p:
            self.add("missing_value", Severity.HIGH, Certainty.OBSERVED, [ev.evidence("conversion without value")],
                     rule_id="ads.conversion.dynamic_value", action="google_ads.fix_conversion_parameters", event="conversion")
        elif isinstance(p["value"], (int, float)) and p["value"] in (0, 1):
            self.add("suspected_static_value", Severity.MEDIUM, Certainty.INFERRED, [ev.evidence(f"conversion value {p['value']}")],
                     rule_id="ads.conversion.dynamic_value", action="google_ads.fix_conversion_parameters", value=p["value"])
        self.check_currency(ev, required="value" in p, rule_id="ads.conversion.dynamic_value")
        if not p.get("transaction_id"):
            self.add("missing_transaction_id", Severity.MEDIUM, Certainty.OBSERVED, [ev.evidence("conversion without transaction id (oid)")],
                     rule_id="ads.conversion.transaction_id", action="google_ads.fix_conversion_parameters", event="conversion")
        # Cross-check with the GA4 purchase value from the same page load.
        ga4 = [e for e in self.ctx.events_for("ga4") if e.name == "purchase" and e.page_load_id == ev.page_load_id]
        if ga4 and isinstance(p.get("value"), (int, float)) and isinstance(ga4[0].params.get("value"), (int, float)):
            gv = float(ga4[0].params["value"])
            if gv > 0 and abs(float(p["value"]) - gv) / gv > 0.01:
                self.add("value_mismatch", Severity.MEDIUM, Certainty.OBSERVED,
                         [ev.evidence(f"conversion value {p['value']}"), ga4[0].evidence(f"GA4 purchase value {gv}")],
                         rule_id="ads.conversion.dynamic_value", action="google_ads.fix_conversion_parameters",
                         value=p["value"], reference=gv)

    def _check_static_value(self, convs: list[PlatformEvent]) -> None:
        by_label: dict[Any, list[PlatformEvent]] = defaultdict(list)
        for ev in convs:
            if ev.params.get("order_ref"):
                by_label[ev.params.get("label")].append(ev)
        for label, evs in by_label.items():
            orders = {e.params.get("order_ref") for e in evs}
            values = {e.params.get("value") for e in evs}
            totals = {e.params.get("order_total") for e in evs if e.params.get("order_total") is not None}
            if len(orders) > 1 and len(values) == 1 and len(totals) > 1:
                self.add("static_value", Severity.HIGH, Certainty.OBSERVED,
                         [e.evidence(f"order {e.params.get('order_ref')} total {e.params.get('order_total')} sent value {e.params.get('value')}") for e in evs],
                         rule_id="ads.conversion.dynamic_value", action="google_ads.fix_conversion_parameters", label=label)

    def _check_dashboard(self) -> None:
        dash = self.dashboard()
        if dash.get("status") != "ok":
            return
        self.tested.append("dashboard_configuration")
        actions = [a for a in dash.get("conversion_actions") or [] if isinstance(a, dict)]
        purchase = [a for a in actions if str(a.get("category", "")).lower() == "purchase" and a.get("primary", True)]
        for a in purchase:
            if str(a.get("value_setting", "")).lower() == "static":
                self.add("static_value", Severity.HIGH, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.DASHBOARD, f"conversion action '{a.get('name')}' uses a static value")],
                         rule_id="ads.conversion.dynamic_value", action="google_ads.fix_conversion_parameters", label=a.get("label"))
        if len(purchase) > 1:
            self.add("conflicting_implementation", Severity.HIGH, Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, f"{len(purchase)} primary purchase conversion actions: {[a.get('name') for a in purchase]}")],
                     action="google_ads.fix_conflicting_implementation", targets=[a.get("name") for a in purchase])
        site_labels = {(e.tracking_id, e.params.get("label")) for e in self.events_named(["conversion"])}
        for a in purchase:
            cid, label = a.get("conversion_id"), a.get("label")
            if cid and label and site_labels and (f"AW-{str(cid).removeprefix('AW-')}", label) not in site_labels:
                self.add("conversion_label_not_observed", Severity.MEDIUM, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.DASHBOARD, f"action '{a.get('name')}' ({cid}/{label}) not seen on storefront")],
                         action="google_ads.configure_purchase_conversion", label=label)

    def decide_status(self) -> ServiceStatus:
        ids, runtime = self.presence_signals()
        has_conv = bool(self.events_named(["conversion"]))
        if ids and self.ctx.behavioral and not has_conv and "purchase" not in self.ctx.steps_completed:
            # The only definitive signal (a conversion) needs a completed order.
            if runtime or self.events():
                self.untested.append("event:conversion")
                confirmed = [f for f in self.findings if f.is_issue and f.certainty == Certainty.OBSERVED and f.severity != Severity.LOW]
                return ServiceStatus.CONNECTED_WITH_ISSUES if confirmed else ServiceStatus.PARTIALLY_VERIFIED
        status = super().decide_status()
        if status == ServiceStatus.CONNECTED_VERIFIED and not has_conv:
            return ServiceStatus.PARTIALLY_VERIFIED
        return status
