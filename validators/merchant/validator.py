"""Google Merchant Center validator (rules: merchant.*).

Runs only in the separate Merchant stage, after the user approved *inspection*.
Its input is what the agent read from the Merchant Center dashboard
(``dashboards.merchant``) plus storefront product pages already observed.
Each finding records where the fix actually belongs (``fix_location``): a
price mismatch usually originates in the Salla product data / feed sync, not
in a Merchant Center setting.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from core.discovery.observation import AuditContext
from core.models import Certainty, Evidence, EvidenceSource, Finding, ServiceResult, ServiceStatus, Severity

ISSUE_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("price_mismatch", re.compile(r"(price.*(mismatch|incorrect|crawl))|((mismatch|mismatched).*price)|سعر", re.I)),
    ("availability_mismatch", re.compile(r"(availability.*(mismatch|crawl))|((mismatch|mismatched).*availab)|توفر", re.I)),
    ("landing_page", re.compile(r"landing page|page not found|404|unavailable (desktop|mobile)|صفحة", re.I)),
    ("identifiers", re.compile(r"gtin|mpn|identifier|brand|معرف", re.I)),
    ("shipping", re.compile(r"shipping|delivery|شحن", re.I)),
    ("policy", re.compile(r"policy|misrepresentation|سياس", re.I)),
)

FIX_LOCATION = {
    "price_mismatch": "salla_store_or_feed",
    "availability_mismatch": "salla_store_or_feed",
    "landing_page": "salla_store",
    "identifiers": "salla_product_data",
    "shipping": "merchant_center",
    "policy": "merchant_center_review",
    "other": "unknown",
}


def _price_number(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"\d+(?:[.,]\d+)?", v.replace(",", ""))
        return float(m.group(0)) if m else None
    return None


def _norm_url(u: str | None) -> str:
    if not u:
        return ""
    p = urlsplit(u)
    return f"{(p.hostname or '').lower()}{p.path.rstrip('/')}"


class MerchantValidator:
    service = "merchant"

    def __init__(self, ctx: AuditContext):
        self.ctx = ctx
        self.findings: list[Finding] = []
        self.tested: list[str] = []
        self.untested: list[str] = []

    def add(self, code: str, severity: Severity, certainty: Certainty, evidence: list[Evidence], rule_id: str | None = None,
            action: str | None = None, **params: Any) -> None:
        self.findings.append(Finding("merchant", code, severity, certainty, evidence, rule_id, params, action))

    def validate(self) -> ServiceResult:
        dash = self.ctx.dashboards.get("merchant") or {}
        status = self._status_from_dashboard(dash)
        if status is not None:
            return self._result(status)
        self._check_account(dash)
        self._check_products(dash)
        self._check_storefront_consistency(dash)
        issues = [f for f in self.findings if f.is_issue]
        if not issues:
            status = ServiceStatus.CONNECTED_VERIFIED if dash.get("products") else ServiceStatus.PARTIALLY_VERIFIED
        elif any(f.code in ("domain_mismatch", "website_not_claimed") for f in issues):
            status = ServiceStatus.MISCONFIGURED
        else:
            status = ServiceStatus.CONNECTED_WITH_ISSUES
        return self._result(status)

    def _status_from_dashboard(self, dash: dict[str, Any]) -> ServiceStatus | None:
        st = dash.get("status")
        if not dash:
            self.untested.append("merchant_dashboard")
            return ServiceStatus.UNABLE_TO_VERIFY
        if st == "auth_required":
            return ServiceStatus.AUTHENTICATION_REQUIRED
        if st in ("captcha", "two_factor", "multiple_accounts", "unexpected_ui"):
            self.add(f"dashboard_{st}", Severity.INFO, Certainty.UNVERIFIED, [Evidence(EvidenceSource.DASHBOARD, f"status {st}")])
            return ServiceStatus.USER_ACTION_REQUIRED
        if st == "permission_denied":
            self.add("dashboard_permission_denied", Severity.INFO, Certainty.UNVERIFIED, [Evidence(EvidenceSource.DASHBOARD, st)])
            return ServiceStatus.UNABLE_TO_VERIFY
        if st == "no_account":
            self.add("not_detected", Severity.MEDIUM, Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, "no Merchant Center account available for this store")], action="merchant.connect")
            return ServiceStatus.NOT_CONNECTED
        if st != "ok":
            return ServiceStatus.ERROR
        return None

    def _check_account(self, dash: dict[str, Any]) -> None:
        self.tested.append("account")
        store_host = (urlsplit(self.ctx.store_url).hostname or "").lower().removeprefix("www.")
        site = dash.get("website_url")
        if site:
            host = (urlsplit(site).hostname or "").lower().removeprefix("www.")
            if host and store_host and host != store_host:
                self.add("domain_mismatch", Severity.HIGH, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.DASHBOARD, f"Merchant website {host} vs store {store_host}")],
                         action="merchant.fix_website_settings", merchant_host=host, store_host=store_host)
        if dash.get("website_claimed") is False:
            self.add("website_not_claimed", Severity.HIGH, Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, "website not verified/claimed")], action="merchant.fix_website_settings")
        for issue in dash.get("account_issues") or []:
            self.add("account_issue", Severity.HIGH, Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, str(issue.get("description") or issue))],
                     action="merchant.review_account_issue", description=str(issue.get("description") or issue.get("code") or ""))
        for ds in dash.get("data_sources") or []:
            if ds.get("status") not in (None, "ok", "active") or (ds.get("last_fetch_errors") or 0) > 0:
                self.add("feed_issue", Severity.MEDIUM, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.DASHBOARD, f"data source {ds.get('name')}: {ds.get('status')}, errors={ds.get('last_fetch_errors')}")],
                         action="merchant.review_data_source", source=ds.get("name"), fix_location="feed")

    def _categorise(self, text: str) -> str:
        for cat, pat in ISSUE_CATEGORIES:
            if pat.search(text):
                return cat
        return "other"

    def _check_products(self, dash: dict[str, Any]) -> None:
        products = [p for p in dash.get("products") or [] if isinstance(p, dict)]
        if not products:
            self.untested.append("product_statuses")
            return
        self.tested.append("product_statuses")
        by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
        disapproved = [p for p in products if str(p.get("status", "")).lower() in ("disapproved", "not_approved", "rejected")]
        for p in products:
            for iss in p.get("issues") or []:
                text = f"{iss.get('code', '')} {iss.get('description', '')} {iss.get('attribute', '')}"
                by_cat[self._categorise(text)].append({"offer_id": p.get("offer_id"), "issue": iss.get("description") or iss.get("code")})
        if disapproved:
            self.add("disapproved_products", Severity.HIGH, Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, f"{len(disapproved)} of {len(products)} products disapproved",
                               data={"sample": [p.get("offer_id") for p in disapproved[:10]]})],
                     count=len(disapproved), total=len(products))
        for cat, rows in by_cat.items():
            self.add(f"issue_{cat}", Severity.HIGH if cat in ("price_mismatch", "availability_mismatch", "landing_page") else Severity.MEDIUM,
                     Certainty.OBSERVED,
                     [Evidence(EvidenceSource.DASHBOARD, f"{len(rows)} product issue(s) in category {cat}", data={"sample": rows[:10]})],
                     rule_id="merchant.landing_page_match" if cat in ("price_mismatch", "availability_mismatch") else "merchant.required_attributes",
                     action=f"merchant.fix_{cat}", count=len(rows), fix_location=FIX_LOCATION[cat])

    def _check_storefront_consistency(self, dash: dict[str, Any]) -> None:
        """Compare Merchant product data with structured data seen on the storefront."""
        products = {_norm_url(p.get("link")): p for p in dash.get("products") or [] if isinstance(p, dict) and p.get("link")}
        compared = 0
        for ld in self.ctx.json_ld_products:
            mc = products.get(_norm_url(ld.get("page_url")))
            if not mc or not ld.get("offers"):
                continue
            compared += 1
            offer = ld["offers"][0]
            sp, mp = _price_number(offer.get("price")), _price_number(mc.get("price"))
            if sp is not None and mp is not None and abs(sp - mp) > 0.009:
                self.add("storefront_price_differs", Severity.HIGH, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.HTML, f"storefront price {sp}", page_url=ld.get("page_url")),
                          Evidence(EvidenceSource.DASHBOARD, f"Merchant price {mp} for {mc.get('offer_id')}")],
                         rule_id="merchant.landing_page_match", action="merchant.fix_price_mismatch",
                         offer_id=mc.get("offer_id"), store_price=sp, merchant_price=mp, fix_location="salla_store_or_feed")
            sa = str(offer.get("availability") or "").lower().rsplit("/", 1)[-1]
            ma = str(mc.get("availability") or "").lower().replace("_", "")
            if sa and ma and sa.replace("_", "") != ma:
                self.add("storefront_availability_differs", Severity.HIGH, Certainty.OBSERVED,
                         [Evidence(EvidenceSource.HTML, f"storefront availability {sa}", page_url=ld.get("page_url")),
                          Evidence(EvidenceSource.DASHBOARD, f"Merchant availability {mc.get('availability')}")],
                         rule_id="merchant.landing_page_match", action="merchant.fix_availability_mismatch",
                         offer_id=mc.get("offer_id"), fix_location="salla_store_or_feed")
        if compared:
            self.tested.append("storefront_consistency")
        else:
            self.untested.append("storefront_consistency")

    def _result(self, status: ServiceStatus) -> ServiceResult:
        dash = self.ctx.dashboards.get("merchant") or {}
        return ServiceResult(
            service="merchant",
            status=status,
            findings=self.findings,
            ids=[str(dash["account_id"])] if dash.get("account_id") else [],
            tested=sorted(set(self.tested)),
            untested=sorted(set(self.untested)),
        )
