"""Meta Pixel validator (rules: meta.*). Meta rules only - not reused elsewhere."""

from __future__ import annotations

from core.models import Certainty, Evidence, EvidenceSource, PlatformEvent, Severity
from validators.base import BaseValidator

COMMERCE = ("ViewContent", "AddToCart", "InitiateCheckout", "AddPaymentInfo", "Purchase")


class MetaValidator(BaseValidator):
    service = "meta"
    expected_events = {
        "home": ("PageView",),
        "view_item": ("ViewContent",),
        "add_to_cart": ("AddToCart",),
        "begin_checkout": ("InitiateCheckout",),
        "add_payment_info": ("AddPaymentInfo",),
        "purchase": ("Purchase",),
    }
    step_bound_events = {"Purchase": ("purchase",)}

    def run_checks(self) -> None:
        for ev in self.events_named(COMMERCE):
            self._check_commerce(ev)
        self.check_same_page_duplicates(("event_id",), names=[*COMMERCE, "PageView"], rule_id="meta.duplicate.browser")
        self._check_event_ids()
        pixels = sorted({e.tracking_id for e in self.decoded_events() if e.tracking_id})
        if len(pixels) > 1:
            self.add("multiple_ids", Severity.LOW, Certainty.INFERRED,
                     [Evidence(EvidenceSource.NETWORK, f"events sent to {len(pixels)} pixels: {pixels}")], ids=pixels)

    def _check_commerce(self, ev: PlatformEvent) -> None:
        p = ev.params
        self.tested.append(f"params:{ev.name}")
        if ev.name == "Purchase":
            if p.get("value") in (None, ""):
                self.add("missing_value", Severity.HIGH, Certainty.OBSERVED, [ev.evidence("Purchase without value")],
                         rule_id="meta.purchase.currency_value", action="meta.fix_event_parameters", event=ev.name)
            elif not isinstance(p.get("value"), (int, float)):
                self.add("value_not_numeric", Severity.HIGH, Certainty.OBSERVED, [ev.evidence(f"Purchase value {p.get('value')!r}")],
                         rule_id="meta.purchase.currency_value", action="meta.fix_event_parameters", event=ev.name, value=str(p.get("value")))
            self.check_currency(ev, required=True, rule_id="meta.purchase.currency_value")
        elif "currency" in p or "value" in p:
            self.check_currency(ev, required="value" in p)
        if not p.get("content_ids") and not p.get("contents"):
            self.add("missing_content_ids", Severity.MEDIUM, Certainty.OBSERVED,
                     [ev.evidence(f"{ev.name} without content_ids/contents")],
                     rule_id="meta.catalog.content_ids", action="meta.fix_event_parameters", event=ev.name)
        elif p.get("content_ids") and p.get("content_type") not in ("product", "product_group"):
            self.add("content_type_missing", Severity.LOW, Certainty.OBSERVED,
                     [ev.evidence(f"{ev.name} content_type={p.get('content_type')!r}")],
                     rule_id="meta.catalog.content_ids", action="meta.fix_event_parameters", event=ev.name)

    def _check_event_ids(self) -> None:
        purchases = self.events_named(["Purchase"])
        capi = self.dashboard().get("conversions_api_active")
        missing = [e for e in purchases if not e.params.get("event_id")]
        if missing and capi:
            self.add("missing_event_id", Severity.HIGH, Certainty.OBSERVED,
                     [e.evidence("Purchase without eventID while Conversions API is active") for e in missing],
                     rule_id="meta.dedup.event_id", action="meta.configure_deduplication", event="Purchase")
        elif missing:
            self.add("missing_event_id", Severity.INFO, Certainty.UNVERIFIED,
                     [e.evidence("Purchase without eventID (only matters if a server-side source also sends it)") for e in missing],
                     rule_id="meta.dedup.event_id")
        if capi is None and self.decoded_events():
            self.untested.append("server_events_deduplication")
