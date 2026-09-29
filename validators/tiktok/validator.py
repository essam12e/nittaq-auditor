"""TikTok Pixel validator (rules: tiktok.*). TikTok rules only."""

from __future__ import annotations

from core.models import Certainty, Evidence, EvidenceSource, PlatformEvent, Severity
from validators.base import BaseValidator

PURCHASE_NAMES = ("Purchase", "CompletePayment", "PlaceAnOrder")
COMMERCE = ("ViewContent", "AddToCart", "InitiateCheckout", "AddPaymentInfo", *PURCHASE_NAMES)


def _content_ids(p: dict) -> list:
    if p.get("content_id"):
        return [p["content_id"]]
    contents = p.get("contents")
    if isinstance(contents, list):
        return [c.get("content_id") for c in contents if isinstance(c, dict) and c.get("content_id")]
    return []


class TikTokValidator(BaseValidator):
    service = "tiktok"
    expected_events = {
        "home": ("Pageview", "PageView"),
        "view_item": ("ViewContent",),
        "add_to_cart": ("AddToCart",),
        "begin_checkout": ("InitiateCheckout",),
        "add_payment_info": ("AddPaymentInfo",),
        "purchase": PURCHASE_NAMES,
    }
    step_bound_events = {n: ("purchase",) for n in PURCHASE_NAMES}

    def run_checks(self) -> None:
        for ev in self.events_named(COMMERCE):
            self._check_commerce(ev)
        for ev in self.events_named(("CompletePayment", "PlaceAnOrder")):
            self.add("legacy_event_name", Severity.LOW, Certainty.OBSERVED, [ev.evidence(f"{ev.name} used")],
                     rule_id="tiktok.purchase.event_name", action="tiktok.fix_event_names", event=ev.name)
            break
        self.check_same_page_duplicates(("event_id",), names=COMMERCE)
        if any(e.parse_confidence == "best_effort" for e in self.events()):
            self.add("best_effort_decoding", Severity.INFO, Certainty.UNVERIFIED,
                     [Evidence(EvidenceSource.NETWORK, "TikTok payload format is not publicly specified; decoded best-effort")],
                     rule_id="net.observed_endpoints")
        if self.decoded_events():
            self.untested.append("server_events_deduplication")

    def _check_commerce(self, ev: PlatformEvent) -> None:
        p = ev.params
        self.tested.append(f"params:{ev.name}")
        is_purchase = ev.name in PURCHASE_NAMES
        if is_purchase and p.get("value") in (None, ""):
            self.add("missing_value", Severity.HIGH, Certainty.OBSERVED, [ev.evidence(f"{ev.name} without value")],
                     rule_id="tiktok.value_currency", action="tiktok.fix_event_parameters", event=ev.name)
        if "value" in p or is_purchase:
            self.check_currency(ev, required=True, rule_id="tiktok.value_currency")
        if not _content_ids(p):
            self.add("missing_content_id", Severity.MEDIUM, Certainty.OBSERVED, [ev.evidence(f"{ev.name} without content_id")],
                     rule_id="tiktok.content_id", action="tiktok.fix_event_parameters", event=ev.name)
