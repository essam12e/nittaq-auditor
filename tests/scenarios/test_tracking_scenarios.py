"""Scenario matrix for tracking validators (spec §42)."""

from __future__ import annotations

import unittest

from core.audit.engine import run_audit
from core.models import Certainty, ServiceStatus
from tests.fixtures.builders import AW, GA, PIXEL, SNAP, TT, Obs, full_ga4, healthy_funnel

S = ServiceStatus


def audit(o: Obs, services: list[str] | None = None):
    return run_audit(o.build(), services)


def codes(res) -> set[str]:
    return {f.code for f in res.findings}


class GA4Scenarios(unittest.TestCase):
    def test_not_installed(self) -> None:
        r = audit(healthy_funnel()).results["ga4"]
        self.assertEqual(r.status, S.NOT_CONNECTED)
        self.assertIn("not_detected", codes(r))

    def test_correct_installation_verified_within_tests(self) -> None:
        r = audit(full_ga4(healthy_funnel())).results["ga4"]
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))
        self.assertTrue(any(u.startswith("event:purchase") for u in r.untested))

    def test_id_detected_but_no_events(self) -> None:
        o = healthy_funnel().gtag_loader()
        r = audit(o).results["ga4"]
        self.assertEqual(r.status, S.MISCONFIGURED)
        self.assertIn("id_detected_no_hits", codes(r))

    def test_id_only_in_markup_is_never_verified(self) -> None:
        o = Obs(behavioral=False).page("home", "<script src='https://www.googletagmanager.com/gtag/js?id=G-ABC1234567'></script>")
        r = audit(o).results["ga4"]
        self.assertEqual(r.status, S.DETECTED)
        self.assertIn("runtime_behaviour", r.untested)

    def test_duplicate_ga4_page_view(self) -> None:
        o = full_ga4(healthy_funnel()).ga4_pageview("home")
        r = audit(o).results["ga4"]
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)
        self.assertIn("duplicate_page_view", codes(r))

    def test_duplicate_purchase_without_transaction_id(self) -> None:
        o = full_ga4(healthy_funnel(True)).ga4("purchase", "purchase").ga4("purchase", "purchase")
        r = audit(o).results["ga4"]
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)
        f = next(f for f in r.findings if f.code == "duplicate_purchase")
        self.assertFalse(f.params["deduplicable"])
        self.assertIn("missing_transaction_id", codes(r))

    def test_duplicate_purchase_same_transaction_is_medium(self) -> None:
        o = full_ga4(healthy_funnel(True)).ga4("purchase", "purchase", tx="T1").ga4("purchase", "purchase", tx="T1")
        f = next(f for f in audit(o).results["ga4"].findings if f.code == "duplicate_purchase")
        self.assertEqual(f.severity.value, "medium")
        self.assertTrue(f.params["deduplicable"])

    def test_missing_transaction_id(self) -> None:
        o = full_ga4(healthy_funnel(True), with_purchase=True)
        r = audit(o).results["ga4"]
        self.assertIn("missing_transaction_id", codes(r))
        self.assertEqual(r.status, S.CONNECTED_WITH_ISSUES)

    def test_empty_transaction_id_is_critical(self) -> None:
        o = full_ga4(healthy_funnel(True), with_purchase=True, tx="")
        f = next(f for f in audit(o).results["ga4"].findings if f.code == "empty_transaction_id")
        self.assertEqual(f.severity.value, "critical")

    def test_static_transaction_id_across_orders(self) -> None:
        o = full_ga4(healthy_funnel(True))
        o.ga4("purchase", "purchase", tx="SAME", extra="ep.order_ref=1001", load=4)
        o.ga4("purchase", "purchase", tx="SAME", extra="ep.order_ref=1002", load=5)
        self.assertIn("static_transaction_id", codes(audit(o).results["ga4"]))

    def test_missing_currency(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item", currency=None).ga4("add_to_cart", "add_to_cart")
        r = audit(o).results["ga4"]
        self.assertIn("missing_currency", codes(r))

    def test_wrong_currency_vs_store(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item", currency="USD").ga4("add_to_cart", "add_to_cart")
        f = next(f for f in audit(o).results["ga4"].findings if f.code == "currency_mismatch")
        self.assertEqual(f.params["store_currency"], "SAR")

    def test_currency_not_forced_to_sar(self) -> None:
        # A store genuinely priced in AED must not be flagged for sending AED.
        home = "<script type='application/ld+json'>{\"@type\":\"Product\",\"offers\":{\"price\":5,\"priceCurrency\":\"AED\"}}</script>"
        o = Obs().funnel("home", "view_item", "add_to_cart", html_home=home)
        o.gtag_loader().ga4_pageview().ga4("view_item", "view_item", currency="AED").ga4("add_to_cart", "add_to_cart", currency="AED")
        r = audit(o).results["ga4"]
        self.assertNotIn("currency_mismatch", codes(r))
        self.assertEqual(r.status, S.CONNECTED_VERIFIED)

    def test_invalid_currency(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item", currency="ريال").ga4("add_to_cart", "add_to_cart")
        self.assertIn("invalid_currency", codes(audit(o).results["ga4"]))

    def test_incorrect_purchase_value(self) -> None:
        o = full_ga4(healthy_funnel(True), with_purchase=True, tx="T1", value=0)
        self.assertIn("zero_value", codes(audit(o).results["ga4"]))
        o2 = full_ga4(healthy_funnel(True), with_purchase=True, tx="T1", value="abc")
        self.assertIn("value_not_numeric", codes(audit(o2).results["ga4"]))

    def test_missing_item_data(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item", items="pr100~qt1").ga4("add_to_cart", "add_to_cart", items=None)
        c = codes(audit(o).results["ga4"])
        self.assertIn("item_missing_id_name", c)
        self.assertIn("missing_items", c)

    def test_unconfirmed_rule_becomes_manual_check(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item").ga4("add_to_cart", "add_to_cart", items=None)
        f = next(f for f in audit(o).results["ga4"].findings if f.code == "missing_items")
        self.assertEqual(f.certainty, Certainty.MANUAL_CHECK)

    def test_purchase_fired_on_wrong_step(self) -> None:
        o = full_ga4(healthy_funnel()).ga4("purchase", "view_item", tx="T1")
        r = audit(o).results["ga4"]
        self.assertIn("event_wrong_step", codes(r))
        self.assertEqual(r.status, S.MISCONFIGURED)

    def test_missing_event_on_completed_step(self) -> None:
        o = healthy_funnel().gtag_loader().ga4_pageview().ga4("view_item", "view_item")
        r = audit(o).results["ga4"]
        self.assertIn("missing_event", codes(r))

    def test_unable_to_verify_static_only(self) -> None:
        r = audit(Obs(behavioral=False).page("home", "<p>no tags</p>")).results["ga4"]
        self.assertEqual(r.status, S.UNABLE_TO_VERIFY)

    def test_multiple_competing_properties_reported_as_inference(self) -> None:
        o = full_ga4(healthy_funnel()).ga4_pageview("home", tid="G-OTHER99999")
        f = next(f for f in audit(o).results["ga4"].findings if f.code == "multiple_ids")
        self.assertEqual(f.certainty, Certainty.INFERRED)

    def test_home_only_is_partial_not_verified(self) -> None:
        o = Obs().funnel("home").gtag_loader().ga4_pageview()
        self.assertEqual(audit(o).results["ga4"].status, S.PARTIALLY_VERIFIED)

    def test_datalayer_event_not_sent(self) -> None:
        o = Obs().page("home", "").page("view_item", "", datalayer=[{"event": "view_item", "ecommerce": {"items": []}}]).page("add_to_cart")
        o.gtag_loader().ga4_pageview().ga4("add_to_cart", "add_to_cart")
        c = codes(audit(o).results["ga4"])
        self.assertIn("missing_event", c)  # step view_item completed, no hit
        self.assertNotIn("datalayer_event_not_sent", c)  # not double-reported


class GTMScenarios(unittest.TestCase):
    def test_not_installed_is_optional(self) -> None:
        r = audit(healthy_funnel()).results["gtm"]
        self.assertEqual(r.status, S.NOT_CONNECTED)
        self.assertEqual(next(f for f in r.findings if f.code == "not_detected").severity.value, "info")

    def test_correct_container_with_dashboard(self) -> None:
        o = healthy_funnel().gtm()
        o.d["pages"][0]["datalayer"] = [{"event": "gtm.js"}, {"event": "gtm.load"}]
        o.dashboard("gtm", status="ok", container_id="GTM-ABCD123", workspace_changes=0, tags=[])
        r = audit(o).results["gtm"]
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))

    def test_container_without_dashboard_is_partial(self) -> None:
        o = healthy_funnel().gtm()
        o.d["pages"][0]["datalayer"] = [{"event": "gtm.js"}]
        self.assertEqual(audit(o).results["gtm"].status, S.PARTIALLY_VERIFIED)

    def test_duplicate_containers(self) -> None:
        o = healthy_funnel().gtm().gtm()
        r = audit(o).results["gtm"]
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)

    def test_duplicate_tags(self) -> None:
        o = healthy_funnel().gtm()
        o.d["pages"][0]["datalayer"] = [{"event": "gtm.js"}]
        o.dashboard("gtm", status="ok", container_id="GTM-ABCD123", workspace_changes=0,
                    tags=[{"name": "GA4 purchase", "type": "gaawe", "measurement_id": GA, "event_name": "purchase"},
                          {"name": "GA4 purchase copy", "type": "gaawe", "measurement_id": GA, "event_name": "purchase"}])
        r = audit(o).results["gtm"]
        self.assertIn("duplicate_tags", codes(r))
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)

    def test_incorrect_trigger(self) -> None:
        o = healthy_funnel().gtm()
        o.d["pages"][0]["datalayer"] = [{"event": "gtm.js"}]
        o.dashboard("gtm", status="ok", container_id="GTM-ABCD123", workspace_changes=0,
                    tags=[{"name": "Ads purchase conversion", "type": "awct", "send_to": AW, "firing_triggers": ["All Pages"]}])
        r = audit(o).results["gtm"]
        self.assertIn("incorrect_trigger", codes(r))
        self.assertEqual(r.status, S.MISCONFIGURED)

    def test_unpublished_changes(self) -> None:
        o = healthy_funnel().gtm()
        o.d["pages"][0]["datalayer"] = [{"event": "gtm.js"}]
        o.dashboard("gtm", status="ok", container_id="GTM-ABCD123", workspace_changes=3, tags=[])
        r = audit(o).results["gtm"]
        self.assertIn("unpublished_changes", codes(r))
        self.assertEqual(r.status, S.CONNECTED_WITH_ISSUES)

    def test_wrong_container_account(self) -> None:
        o = healthy_funnel().gtm()
        o.dashboard("gtm", status="ok", container_id="GTM-ZZZZ999", workspace_changes=0, tags=[])
        r = audit(o).results["gtm"]
        self.assertIn("wrong_container", codes(r))
        self.assertEqual(r.status, S.MISCONFIGURED)

    def test_dashboard_login_required(self) -> None:
        o = healthy_funnel().gtm()
        o.dashboard("gtm", status="auth_required")
        r = audit(o).results["gtm"]
        self.assertIn("dashboard_auth_required", codes(r))
        self.assertIn("dashboard_configuration", r.untested)


class GoogleAdsScenarios(unittest.TestCase):
    def purchase_obs(self) -> Obs:
        o = healthy_funnel(True).gtag_loader(AW)
        full_ga4(o, with_purchase=True, tx="ORDER1", value=250.5)
        return o

    def test_not_connected(self) -> None:
        self.assertEqual(audit(healthy_funnel()).results["google_ads"].status, S.NOT_CONNECTED)

    def test_correct_conversion(self) -> None:
        o = self.purchase_obs().ads().ads(endpoint="1p-conversion")  # normal paired requests
        r = audit(o).results["google_ads"]
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))
        self.assertNotIn("duplicate_conversion", codes(r))

    def test_tag_present_but_purchase_untestable(self) -> None:
        r = audit(healthy_funnel().gtag_loader(AW)).results["google_ads"]
        self.assertEqual(r.status, S.PARTIALLY_VERIFIED)
        self.assertIn("event:conversion", r.untested)

    def test_duplicate_conversion(self) -> None:
        o = self.purchase_obs().ads(oid=None).ads(oid=None)
        r = audit(o).results["google_ads"]
        self.assertIn("duplicate_conversion", codes(r))
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)

    def test_static_value(self) -> None:
        o = self.purchase_obs().ads(value=1)
        self.assertIn("suspected_static_value", codes(audit(o).results["google_ads"]))
        o2 = self.purchase_obs().ads()
        o2.dashboard("google_ads", status="ok", conversion_actions=[
            {"name": "Purchase", "category": "purchase", "value_setting": "static", "conversion_id": "123456789", "label": "AbCdEf"}])
        self.assertIn("static_value", codes(audit(o2).results["google_ads"]))

    def test_missing_transaction_id(self) -> None:
        o = self.purchase_obs().ads(oid=None)
        self.assertIn("missing_transaction_id", codes(audit(o).results["google_ads"]))

    def test_incorrect_currency(self) -> None:
        o = self.purchase_obs().ads(currency="USD")
        self.assertIn("currency_mismatch", codes(audit(o).results["google_ads"]))

    def test_value_mismatch_with_ga4(self) -> None:
        o = self.purchase_obs().ads(value=999)
        self.assertIn("value_mismatch", codes(audit(o).results["google_ads"]))

    def test_conflicting_implementation(self) -> None:
        o = self.purchase_obs().ads().ads(aw="AW-987654321", label="Other")
        self.assertIn("conflicting_implementation", codes(audit(o).results["google_ads"]))

    def test_conversion_action_existing_is_not_proof(self) -> None:
        o = healthy_funnel()
        o.dashboard("google_ads", status="ok", conversion_actions=[{"name": "Purchase", "category": "purchase", "value_setting": "dynamic"}])
        self.assertEqual(audit(o).results["google_ads"].status, S.NOT_CONNECTED)


class MetaScenarios(unittest.TestCase):
    def base(self) -> Obs:
        o = healthy_funnel()
        o.meta("PageView", "home").meta("ViewContent", "view_item", content_ids=["SKU1"], content_type="product")
        return o

    def test_not_connected(self) -> None:
        self.assertEqual(audit(healthy_funnel()).results["meta"].status, S.NOT_CONNECTED)

    def test_correct(self) -> None:
        o = self.base().meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        r = audit(o).results["meta"]
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))
        self.assertIn(PIXEL, r.ids)

    def test_duplicate_events(self) -> None:
        o = self.base()
        for _ in range(2):
            o.meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        self.assertEqual(audit(o).results["meta"].status, S.DUPLICATE_EVENTS)

    def test_missing_parameters_on_purchase(self) -> None:
        o = self.base().meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        o.page("purchase").meta("Purchase", "purchase")
        c = codes(audit(o).results["meta"])
        self.assertTrue({"missing_value", "missing_currency", "missing_content_ids"} <= c)

    def test_conflicting_implementations_two_pixels(self) -> None:
        o = self.base().meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        o.meta("PageView", "home", pixel="999888777666")
        self.assertIn("multiple_ids", codes(audit(o).results["meta"]))

    def test_unable_to_verify_without_browser(self) -> None:
        o = Obs(behavioral=False).page("home", "<script>fbq('init', '1234567890');</script>")
        self.assertEqual(audit(o).results["meta"].status, S.DETECTED)
        o2 = Obs(behavioral=False).page("home", "<p></p>")
        self.assertEqual(audit(o2).results["meta"].status, S.UNABLE_TO_VERIFY)

    def test_missing_event_id_with_capi(self) -> None:
        o = self.base().meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        o.page("purchase").meta("Purchase", "purchase", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
        o.dashboard("meta", status="ok", conversions_api_active=True)
        f = next(f for f in audit(o).results["meta"].findings if f.code == "missing_event_id")
        self.assertEqual(f.severity.value, "high")


class TikTokScenarios(unittest.TestCase):
    def base(self) -> Obs:
        return healthy_funnel().tiktok("Pageview", "home").tiktok("ViewContent", "view_item", content_id="SKU1", value=100, currency="SAR")

    def test_not_connected(self) -> None:
        self.assertEqual(audit(healthy_funnel()).results["tiktok"].status, S.NOT_CONNECTED)

    def test_correct_is_partial_without_test_events_confirmation(self) -> None:
        o = self.base().tiktok("AddToCart", "add_to_cart", content_id="SKU1", value=100, currency="SAR")
        r = audit(o).results["tiktok"]
        self.assertEqual(r.status, S.PARTIALLY_VERIFIED, codes(r))
        self.assertIn("platform_test_events_confirmation", r.untested)
        o.dashboard("tiktok", status="ok", test_events_confirmed=True)
        self.assertEqual(audit(o).results["tiktok"].status, S.CONNECTED_VERIFIED)
        self.assertIn(TT, r.ids)

    def test_duplicate(self) -> None:
        o = self.base()
        for _ in range(2):
            o.tiktok("AddToCart", "add_to_cart", content_id="SKU1", value=100, currency="SAR")
        self.assertEqual(audit(o).results["tiktok"].status, S.DUPLICATE_EVENTS)

    def test_missing_parameters_and_legacy_name(self) -> None:
        o = self.base().tiktok("AddToCart", "add_to_cart").page("purchase").tiktok("CompletePayment", "purchase")
        c = codes(audit(o).results["tiktok"])
        self.assertTrue({"missing_content_id", "missing_value", "missing_currency", "legacy_event_name"} <= c)

    def test_unparsed_payload(self) -> None:
        o = healthy_funnel().req("https://analytics.tiktok.com/api/v2/pixel", "home", "not-json")
        self.assertEqual(audit(o).results["tiktok"].status, S.CONNECTED_UNVERIFIED)


class SnapchatScenarios(unittest.TestCase):
    def base(self) -> Obs:
        return healthy_funnel().snap("PAGE_VIEW", "home").snap("VIEW_CONTENT", "view_item", item_ids=["SKU1"]).snap("ADD_CART", "add_to_cart", item_ids=["SKU1"])

    def test_not_connected(self) -> None:
        self.assertEqual(audit(healthy_funnel()).results["snapchat"].status, S.NOT_CONNECTED)

    def test_correct_partial_then_verified(self) -> None:
        o = self.base()
        self.assertEqual(audit(o).results["snapchat"].status, S.PARTIALLY_VERIFIED)
        o.dashboard("snapchat", status="ok", test_events_confirmed=True)
        r = audit(o).results["snapchat"]
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))
        self.assertIn(SNAP, r.ids)

    def test_purchase_parameters(self) -> None:
        o = self.base().page("purchase").snap("PURCHASE", "purchase")
        c = codes(audit(o).results["snapchat"])
        self.assertTrue({"missing_transaction_id", "missing_price", "missing_currency", "missing_item_ids"} <= c)

    def test_duplicate_purchase_across_reloads(self) -> None:
        o = self.base().page("purchase")
        kw = dict(transaction_id="O1", price=100, currency="SAR", item_ids=["SKU1"], number_items=1)
        o.snap("PURCHASE", "purchase", load=4, **kw).snap("PURCHASE", "purchase", load=5, **kw)
        r = audit(o).results["snapchat"]
        self.assertIn("duplicate_purchase", codes(r))
        self.assertEqual(r.status, S.DUPLICATE_EVENTS)


class CrossPlatformScenarios(unittest.TestCase):
    def test_ga4_direct_and_through_gtm(self) -> None:
        o = full_ga4(healthy_funnel()).gtm().ga4_pageview("home")
        a = audit(o)
        self.assertIn("ga4_direct_and_gtm", {f.code for f in a.cross_platform})

    def test_purchase_value_mismatch_between_platforms(self) -> None:
        o = full_ga4(healthy_funnel(True), with_purchase=True, tx="T1", value=100)
        o.meta("Purchase", "purchase", value=150, currency="SAR", content_ids=["SKU1"], content_type="product")
        self.assertIn("cross_platform_value_mismatch", {f.code for f in audit(o).cross_platform})

    def test_duplicates_are_reported_never_removed(self) -> None:
        o = full_ga4(healthy_funnel()).gtm().ga4_pageview("home")
        before = o.build()
        run_audit(before)
        self.assertEqual(before, o.build())  # audit is a pure read


class PageLevelFailures(unittest.TestCase):
    def test_store_not_loading(self) -> None:
        o = Obs().page("home", status="error")
        for r in audit(o).results.values():
            self.assertEqual(r.status, S.ERROR)

    def test_store_behind_captcha(self) -> None:
        o = Obs().page("home", status="captcha")
        self.assertEqual(audit(o).results["ga4"].status, S.USER_ACTION_REQUIRED)


if __name__ == "__main__":
    unittest.main()
