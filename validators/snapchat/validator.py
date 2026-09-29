"""Snapchat Pixel validator (rules: snap.*). Snapchat rules only."""

from __future__ import annotations

from collections import defaultdict

from core.models import Certainty, Evidence, EvidenceSource, PlatformEvent, Severity
from validators.base import BaseValidator

COMMERCE = ("VIEW_CONTENT", "ADD_CART", "START_CHECKOUT", "ADD_BILLING", "PURCHASE")


class SnapchatValidator(BaseValidator):
    service = "snapchat"
    expected_events = {
        "home": ("PAGE_VIEW",),
        "view_item": ("VIEW_CONTENT",),
        "add_to_cart": ("ADD_CART",),
        "begin_checkout": ("START_CHECKOUT",),
        "purchase": ("PURCHASE",),
    }
    step_bound_events = {"PURCHASE": ("purchase",)}

    def run_checks(self) -> None:
        for ev in self.events_named(["PURCHASE"]):
            self._check_purchase(ev)
        for ev in self.events_named(COMMERCE):
            if ev.name != "PURCHASE" and not ev.params.get("item_ids"):
                self.add("missing_item_ids", Severity.LOW, Certainty.OBSERVED, [ev.evidence(f"{ev.name} without item_ids")],
                         rule_id="snap.event_names", action="snapchat.fix_event_parameters", event=ev.name)
        self.check_same_page_duplicates(("client_dedup_id",), names=COMMERCE)
        self._check_repeated_transaction()
        if any(e.parse_confidence == "best_effort" for e in self.events()):
            self.add("best_effort_decoding", Severity.INFO, Certainty.UNVERIFIED,
                     [Evidence(EvidenceSource.NETWORK, "Snap Pixel payload format is not publicly specified; decoded best-effort")],
                     rule_id="net.observed_endpoints")

    def _check_purchase(self, ev: PlatformEvent) -> None:
        p = ev.params
        self.tested.append("params:PURCHASE")
        checks = (
            ("transaction_id", "missing_transaction_id", Severity.HIGH),
            ("price", "missing_price", Severity.HIGH),
            ("item_ids", "missing_item_ids", Severity.MEDIUM),
            ("number_items", "missing_number_items", Severity.LOW),
        )
        for key, code, sev in checks:
            if p.get(key) in (None, "", []):
                self.add(code, sev, Certainty.OBSERVED, [ev.evidence(f"PURCHASE without {key}")],
                         rule_id="snap.purchase.params", action="snapchat.fix_event_parameters", event="PURCHASE")
        self.check_currency(ev, required=True, rule_id="snap.purchase.params")

    def _check_repeated_transaction(self) -> None:
        by_tid: dict[str, list[PlatformEvent]] = defaultdict(list)
        for ev in self.events_named(["PURCHASE"]):
            if ev.params.get("transaction_id"):
                by_tid[str(ev.params["transaction_id"])].append(ev)
        for tid, evs in by_tid.items():
            loads = {e.page_load_id for e in evs}
            if len(evs) > 1 and len(loads) > 1:
                # e.g. thank-you page reload re-firing PURCHASE for the same order
                self.add("duplicate_purchase", Severity.HIGH, Certainty.OBSERVED,
                         [e.evidence(f"PURCHASE {tid} in page load {e.page_load_id}") for e in evs],
                         action="snapchat.fix_duplicate_events", event="PURCHASE", count=len(evs), transaction_id=tid)
