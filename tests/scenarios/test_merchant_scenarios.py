"""Merchant Center scenarios (spec §29-31, §42)."""

from __future__ import annotations

import unittest

from core.audit.engine import run_merchant_inspection
from core.models import ServiceStatus
from tests.fixtures.builders import Obs

S = ServiceStatus
PRODUCT_LD = ("<script type='application/ld+json'>{\"@type\":\"Product\",\"sku\":\"SKU1\",\"offers\":{\"price\":\"%s\","
              "\"priceCurrency\":\"SAR\",\"availability\":\"https://schema.org/%s\"}}</script>")


def merchant_obs(products: list[dict], store_price: str = "100", availability: str = "InStock", **dash) -> Obs:
    o = Obs(adapter="claude:playwright-mcp").page("view_item", PRODUCT_LD % (store_price, availability))
    o.dashboard("merchant", status=dash.pop("status", "ok"), account_id="555", website_url=dash.pop("website_url", "https://store.example.com"),
                website_claimed=dash.pop("website_claimed", True), products=products, **dash)
    return o


def product(offer_id: str = "SKU1", status: str = "approved", issues: list | None = None, price: str = "100 SAR",
            availability: str = "in_stock") -> dict:
    return {"offer_id": offer_id, "status": status, "price": price, "availability": availability,
            "link": "https://store.example.com/shirt/p1234567", "issues": issues or []}


def inspect(o: Obs):
    return run_merchant_inspection(o.build()).results["merchant"]


def codes(r) -> set[str]:
    return {f.code for f in r.findings}


class MerchantScenarios(unittest.TestCase):
    def test_healthy_products(self) -> None:
        r = inspect(merchant_obs([product()]))
        self.assertEqual(r.status, S.CONNECTED_VERIFIED, codes(r))
        self.assertIn("storefront_consistency", r.tested)

    def test_disapproved_products(self) -> None:
        r = inspect(merchant_obs([product(status="disapproved", issues=[{"code": "policy_violation", "description": "Misrepresentation"}])]))
        self.assertIn("disapproved_products", codes(r))
        self.assertIn("issue_policy", codes(r))
        self.assertEqual(r.status, S.CONNECTED_WITH_ISSUES)

    def test_price_mismatch_points_to_store(self) -> None:
        r = inspect(merchant_obs([product(price="90 SAR", issues=[{"description": "Mismatched value (page crawl) [price]"}])]))
        f = next(f for f in r.findings if f.code == "issue_price_mismatch")
        self.assertEqual(f.params["fix_location"], "salla_store_or_feed")
        g = next(f for f in r.findings if f.code == "storefront_price_differs")
        self.assertEqual((g.params["store_price"], g.params["merchant_price"]), (100.0, 90.0))

    def test_availability_mismatch(self) -> None:
        r = inspect(merchant_obs([product(availability="out_of_stock")]))
        self.assertIn("storefront_availability_differs", codes(r))

    def test_landing_page_problem(self) -> None:
        r = inspect(merchant_obs([product(status="disapproved", issues=[{"description": "Unavailable desktop landing page"}])]))
        f = next(f for f in r.findings if f.code == "issue_landing_page")
        self.assertEqual(f.params["fix_location"], "salla_store")

    def test_identifier_problem(self) -> None:
        r = inspect(merchant_obs([product(issues=[{"description": "Missing value [gtin]"}])]))
        self.assertEqual(next(f for f in r.findings if f.code == "issue_identifiers").params["fix_location"], "salla_product_data")

    def test_multiple_issues(self) -> None:
        r = inspect(merchant_obs([
            product("A", "disapproved", [{"description": "Mismatched value (page crawl) [price]"}]),
            product("B", "disapproved", [{"description": "Missing value [gtin]"}, {"description": "Incorrect shipping cost"}]),
        ], account_issues=[{"description": "Misrepresentation"}]))
        self.assertTrue({"issue_price_mismatch", "issue_identifiers", "issue_shipping", "account_issue", "disapproved_products"} <= codes(r))

    def test_domain_mismatch_is_misconfigured(self) -> None:
        r = inspect(merchant_obs([product()], website_url="https://other-shop.com"))
        self.assertEqual(r.status, S.MISCONFIGURED)

    def test_login_required(self) -> None:
        o = Obs().page("home")
        o.dashboard("merchant", status="auth_required")
        self.assertEqual(inspect(o).status, S.AUTHENTICATION_REQUIRED)

    def test_multiple_accounts_needs_user(self) -> None:
        o = Obs().page("home")
        o.dashboard("merchant", status="multiple_accounts")
        self.assertEqual(inspect(o).status, S.USER_ACTION_REQUIRED)

    def test_no_dashboard_data(self) -> None:
        self.assertEqual(inspect(Obs().page("home")).status, S.UNABLE_TO_VERIFY)


if __name__ == "__main__":
    unittest.main()
