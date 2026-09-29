"""Salla knowledge adapter.

Salla stores are not generic HTML sites: the storefront is built on the
Twilight engine (JS SDK served from cdn.salla.network), marketing
integrations (GTM, GA4, Meta/TikTok/Snapchat pixels, Meta CAPI) are configured
from the merchant dashboard / Salla App Store, and Salla exposes its own
ecommerce event stream (Device Mode / Cloud Mode) to apps.

Every Salla-specific assumption here is backed by an entry in
``knowledge/salla/*.md`` and ``knowledge/rules.json``; URL heuristics that are
*not* documented by Salla are marked ``documented=False`` and are only used as
hints (the collected observation's explicit ``step`` label always wins).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Salla ecommerce events (Device Mode / Cloud Mode) as documented at
# https://docs.salla.dev/1804461m0 (cart & checkout) and product events.
SALLA_EVENTS_TO_FUNNEL = {
    "Product Viewed": "view_item",
    "Product Added": "add_to_cart",
    "Product Removed": "remove_from_cart",
    "Cart Viewed": "view_cart",
    "Checkout Started": "begin_checkout",
    "Payment Info Entered": "add_payment_info",
    "Order Completed": "purchase",
}

FUNNEL_STEPS = ("home", "view_item", "add_to_cart", "view_cart", "begin_checkout", "add_payment_info", "purchase")

# Steps the auditor can exercise without creating any financial transaction.
SAFE_TEST_STEPS = ("home", "view_item", "add_to_cart", "view_cart", "begin_checkout")


@dataclass(frozen=True)
class UrlHeuristic:
    step: str
    pattern: re.Pattern[str]
    documented: bool


# NOTE: undocumented heuristics observed on Salla storefronts; hints only.
URL_HEURISTICS: tuple[UrlHeuristic, ...] = (
    UrlHeuristic("view_item", re.compile(r"/p\d{5,}(?:[/?#]|$)"), documented=False),
    UrlHeuristic("view_cart", re.compile(r"/cart(?:[/?#]|$)"), documented=False),
    UrlHeuristic("begin_checkout", re.compile(r"/checkout(?:[/?#]|$)"), documented=False),
)

ADD_TO_CART_LABELS = ("إضافة للسلة", "أضف للسلة", "اضف للسلة", "إضافة إلى السلة", "أضف إلى السلة", "Add to cart", "Add to Cart")
CHECKOUT_LABELS = ("إتمام الطلب", "اتمام الطلب", "إكمال الطلب", "Checkout", "Complete order")

# Buttons that could create an order or payment. The browser flow must never
# click these (see adapters/browser/controller.py SafetyPolicy).
FORBIDDEN_ACTION_LABELS = (
    "ادفع",
    "إدفع",
    "الدفع الآن",
    "إتمام الدفع",
    "اتمام الدفع",
    "تأكيد الطلب",
    "تاكيد الطلب",
    "تأكيد الدفع",
    "اطلب الآن",
    "شراء الآن",
    "pay now",
    "pay",
    "place order",
    "confirm order",
    "confirm payment",
    "buy now",
    "complete purchase",
)


def classify_page(url: str) -> str | None:
    path = urlsplit(url).path or "/"
    if path in ("", "/") or re.fullmatch(r"/(ar|en)/?", path):
        return "home"
    for h in URL_HEURISTICS:
        if h.pattern.search(path):
            return h.step
    return None


def is_product_link(href: str) -> bool:
    return URL_HEURISTICS[0].pattern.search(urlsplit(href).path or "") is not None


def is_salla_store(salla_signals: list[str], headers: dict[str, str] | None = None) -> tuple[bool, list[str]]:
    """Return (is_salla, reasons). Requires at least one strong storefront marker."""
    reasons = list(dict.fromkeys(salla_signals))
    strong = {"cdn.salla.network", "twilight_sdk", "salla_web_components", "salla_js_global"}
    if headers:
        for k, v in headers.items():
            if "salla" in k.lower() or "salla" in str(v).lower():
                reasons.append(f"header:{k.lower()}")
                strong.add(f"header:{k.lower()}")
    return any(r in strong for r in reasons), reasons
