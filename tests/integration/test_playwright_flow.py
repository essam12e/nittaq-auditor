"""Real browser (Playwright + Chromium) against the local fake store.

These tests exercise the actual adapter, flow, parser and validators. They are
skipped - never faked - when Playwright/Chromium is unavailable.
"""

from __future__ import annotations

import os
import unittest

from tests.fixtures.fake_store import GA, PIXEL, FakeStore, route_handler

try:
    from adapters.browser.controller import Locator, UnsafeAction
    from adapters.browser.flow import StorefrontFlow
    from adapters.browser.playwright_adapter import PlaywrightAdapter, playwright_available

    _AVAILABLE = playwright_available()
except Exception:  # noqa: BLE001
    _AVAILABLE = False

from core.audit.engine import run_audit
from core.models import ServiceStatus


def _browser() -> PlaywrightAdapter:
    return PlaywrightAdapter(route_handler=route_handler)


@unittest.skipUnless(_AVAILABLE and os.environ.get("NITTAQ_SKIP_BROWSER") != "1", "Playwright/Chromium not available")
class PlaywrightFlowTest(unittest.TestCase):
    def run_flow(self, variant: str) -> dict:
        with FakeStore(variant) as store, _browser() as b:
            obs = StorefrontFlow(b).run(store.url)
        return obs

    def test_ok_store_flow_and_classification(self) -> None:
        obs = self.run_flow("ok")
        self.assertEqual(obs["capabilities"], {"javascript": True, "network_capture": True, "interaction": True})
        flow = obs["flow"]
        self.assertEqual(flow["completed"][:4], ["home", "view_item", "add_to_cart", "view_cart"])
        self.assertEqual(flow["blocked"].get("begin_checkout"), "customer_login")
        self.assertEqual(flow["blocked"].get("purchase"), "financial_transaction")
        audit = run_audit(obs)
        ga4 = audit.results["ga4"]
        self.assertIn(GA, ga4.ids)
        self.assertEqual(ga4.status, ServiceStatus.CONNECTED_VERIFIED, [f.code for f in ga4.findings])
        self.assertIn("add_to_cart", ga4.events_seen)
        self.assertIn("begin_checkout", ga4.events_seen)
        self.assertTrue(any("purchase" in u for u in ga4.untested))
        meta = audit.results["meta"]
        self.assertIn(PIXEL, meta.ids)
        self.assertEqual(meta.status, ServiceStatus.CONNECTED_VERIFIED, [f.code for f in meta.findings])
        self.assertEqual(audit.results["tiktok"].status, ServiceStatus.NOT_CONNECTED)
        self.assertEqual(audit.results["google_ads"].status, ServiceStatus.NOT_CONNECTED)
        self.assertTrue(audit.context["is_salla"])
        self.assertEqual(audit.context["store_currency"], "SAR")

    def test_broken_store_detects_issues(self) -> None:
        audit = run_audit(self.run_flow("broken"))
        ga_codes = {f.code for f in audit.results["ga4"].findings}
        self.assertIn("missing_currency", ga_codes)
        self.assertEqual(audit.results["ga4"].status, ServiceStatus.CONNECTED_WITH_ISSUES)
        meta = audit.results["meta"]
        self.assertIn("duplicate_event", {f.code for f in meta.findings})
        self.assertEqual(meta.status, ServiceStatus.DUPLICATE_EVENTS)

    def test_never_clicks_payment_controls(self) -> None:
        with FakeStore("ok") as store, _browser() as b:
            b.open(store.url + "shirt/p1234567", "view_item")
            with self.assertRaises(UnsafeAction):
                b.click(Locator(css="#buy"), "view_item")
            with self.assertRaises(UnsafeAction):
                b.click(Locator(role="button", name="ادفع الآن"), "view_item")
            paid = b._page.evaluate("() => window.NQ_PAID === true")  # noqa: SLF001 - test introspection
            self.assertFalse(paid)
            self.assertFalse(any("en=purchase" in (r.get("post_data") or "") for r in b.network_log()))

    def test_navigation_failure_is_reported(self) -> None:
        with FakeStore("ok") as store, _browser() as b:
            res = b.open(store.url + "missing-page", "home")
        self.assertEqual(res.status, "error")


if __name__ == "__main__":
    unittest.main()
