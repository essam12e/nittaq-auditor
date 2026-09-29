"""Google Analytics 4 validator (rules: knowledge/rules.json ga4.*)."""

from __future__ import annotations

from collections import defaultdict

from core.models import Certainty, Evidence, EvidenceSource, PlatformEvent, Severity
from validators.base import BaseValidator

ECOMMERCE_EVENTS = ("view_item", "add_to_cart", "view_cart", "begin_checkout", "add_payment_info", "purchase")
VALUE_EVENTS = ECOMMERCE_EVENTS


class GA4Validator(BaseValidator):
    service = "ga4"
    expected_events = {
        "home": ("page_view",),
        "view_item": ("view_item",),
        "add_to_cart": ("add_to_cart",),
        "view_cart": ("view_cart",),
        "begin_checkout": ("begin_checkout",),
        "add_payment_info": ("add_payment_info",),
        "purchase": ("purchase",),
    }
    step_bound_events = {"purchase": ("purchase",)}

    def run_checks(self) -> None:
        for ev in self.events_named(ECOMMERCE_EVENTS):
            self._check_ecommerce_event(ev)
        self._check_purchase_ids()
        self.check_same_page_duplicates(("transaction_id",), names=["purchase"], rule_id="ga4.duplicate.purchase")
        self.check_same_page_duplicates(names=[n for n in ECOMMERCE_EVENTS if n != "purchase"])
        self._check_page_view_duplicates()
        self._check_multiple_properties()
        self._check_datalayer_without_hits()

    # ------------------------------------------------------------------
    def _check_ecommerce_event(self, ev: PlatformEvent) -> None:
        p = ev.params
        has_value = "value" in p and p.get("value") not in (None, "")
        if has_value:
            if not isinstance(p["value"], (int, float)):
                self.add(
                    "value_not_numeric",
                    Severity.HIGH if ev.name == "purchase" else Severity.MEDIUM,
                    Certainty.OBSERVED,
                    [ev.evidence(f"{ev.name} value {p['value']!r} is not numeric")],
                    action="ga4.fix_event_parameters",
                    event=ev.name,
                    value=str(p["value"]),
                )
            self.check_currency(ev, required=True, rule_id="ga4.currency.required_with_value")
        elif "currency" in p:
            self.check_currency(ev, required=False)
        elif ev.name == "purchase":
            self.add(
                "missing_value",
                Severity.HIGH,
                Certainty.OBSERVED,
                [ev.evidence("purchase sent without value")],
                action="ga4.fix_event_parameters",
                event=ev.name,
            )

        items = p.get("items")
        if not items:
            self.add(
                "missing_items",
                Severity.MEDIUM,
                Certainty.OBSERVED,
                [ev.evidence(f"{ev.name} sent without items")],
                rule_id="ga4.items.required",
                action="ga4.fix_event_parameters",
                event=ev.name,
            )
        else:
            bad = [i for i, it in enumerate(items) if not (it.get("item_id") or it.get("item_name"))]
            if bad:
                self.add(
                    "item_missing_id_name",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [ev.evidence(f"{ev.name}: {len(bad)} item(s) without item_id/item_name")],
                    rule_id="ga4.items.id_or_name",
                    action="ga4.fix_event_parameters",
                    event=ev.name,
                    count=len(bad),
                )
            if ev.name == "purchase" and has_value and isinstance(p.get("value"), (int, float)):
                self._check_value_against_items(ev, items)
        if ev.name in ("purchase",):
            self.tested.append("params:purchase")
        else:
            self.tested.append(f"params:{ev.name}")

    def _check_value_against_items(self, ev: PlatformEvent, items: list[dict]) -> None:
        try:
            total = sum(float(it.get("price", 0) or 0) * float(it.get("quantity", 1) or 1) for it in items)
        except (TypeError, ValueError):
            return
        value = float(ev.params["value"])
        if value == 0 and total > 0:
            self.add(
                "zero_value",
                Severity.HIGH,
                Certainty.OBSERVED,
                [ev.evidence(f"purchase value 0 while items total {total:.2f}")],
                action="ga4.fix_event_parameters",
                event=ev.name,
                items_total=round(total, 2),
            )
        elif total > 0 and abs(value - total) / total > 0.5:
            # Shipping, tax and discounts legitimately move value away from the
            # item total, so this is an inference, not an observed violation.
            self.add(
                "value_items_mismatch",
                Severity.LOW,
                Certainty.INFERRED,
                [ev.evidence(f"purchase value {value} vs items total {total:.2f}")],
                action="ga4.fix_event_parameters",
                event=ev.name,
                value=value,
                items_total=round(total, 2),
            )

    def _check_purchase_ids(self) -> None:
        purchases = self.events_named(["purchase"])
        by_tid: dict[str, list[PlatformEvent]] = defaultdict(list)
        for ev in purchases:
            tid = ev.params.get("transaction_id")
            if tid is None:
                self.add(
                    "missing_transaction_id",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [ev.evidence("purchase without transaction_id")],
                    rule_id="ga4.purchase.transaction_id_required",
                    action="ga4.fix_event_parameters",
                    event="purchase",
                )
            elif str(tid).strip() == "":
                self.add(
                    "empty_transaction_id",
                    Severity.CRITICAL,
                    Certainty.OBSERVED,
                    [ev.evidence("purchase with empty transaction_id")],
                    rule_id="ga4.transaction_id.not_empty",
                    action="ga4.fix_event_parameters",
                    event="purchase",
                )
            else:
                by_tid[str(tid)].append(ev)
        # The same transaction_id across *different* orders proves a static ID.
        # Orders are distinguished by the agent/adapter via params.order_ref
        # (store order number) or distinct page loads of separate test orders.
        for tid, evs in by_tid.items():
            orders = {e.params.get("order_ref") for e in evs if e.params.get("order_ref")}
            if len(orders) > 1:
                self.add(
                    "static_transaction_id",
                    Severity.CRITICAL,
                    Certainty.OBSERVED,
                    [e.evidence(f"order {e.params.get('order_ref')} sent transaction_id {tid}") for e in evs],
                    rule_id="ga4.transaction_id.unique",
                    action="ga4.fix_event_parameters",
                    transaction_id=tid,
                    orders=len(orders),
                )
        if purchases:
            self.tested.append("transaction_id")

    def _check_page_view_duplicates(self) -> None:
        groups: dict[tuple, list[PlatformEvent]] = defaultdict(list)
        for ev in self.events_named(["page_view"]):
            if ev.page_load_id is not None:
                groups[(ev.tracking_id, ev.page_load_id)].append(ev)
        for (tid, _pl), evs in groups.items():
            if len(evs) > 1:
                self.add(
                    "duplicate_page_view",
                    Severity.HIGH,
                    Certainty.OBSERVED,
                    [e.evidence(f"page_view #{i + 1} to {tid}") for i, e in enumerate(evs)],
                    rule_id="ga4.duplicate.page_view",
                    action="ga4.fix_duplicate_events",
                    fact=True,
                    tracking_id=tid,
                    count=len(evs),
                )
                break  # one finding per property is enough evidence

    def _check_multiple_properties(self) -> None:
        tids = sorted({e.tracking_id for e in self.decoded_events() if e.tracking_id})
        if len(tids) > 1:
            self.add(
                "multiple_ids",
                Severity.LOW,
                Certainty.INFERRED,
                [Evidence(EvidenceSource.NETWORK, f"hits sent to {len(tids)} GA4 properties: {tids}")],
                ids=tids,
            )

    def _check_datalayer_without_hits(self) -> None:
        dl_events = {d["entry"].get("event") for d in self.ctx.datalayer_events()}
        hit_names = {e.name for e in self.decoded_events()}
        already = {f.params.get("event") for f in self.findings if f.code == "missing_event"}
        for name in ECOMMERCE_EVENTS:
            if name in dl_events and name not in hit_names and name not in already and self.ctx.behavioral:
                self.add(
                    "datalayer_event_not_sent",
                    Severity.MEDIUM,
                    Certainty.OBSERVED,
                    [Evidence(EvidenceSource.DATALAYER, f"dataLayer has '{name}' but no GA4 {name} hit was captured")],
                    action="ga4.fix_missing_events",
                    event=name,
                )
