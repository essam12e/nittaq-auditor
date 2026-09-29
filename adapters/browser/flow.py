"""Safe storefront test flow, independent of the browser provider.

home -> product -> add to cart -> cart -> (try) checkout. It stops before any
payment: add_payment_info and purchase are always recorded as blocked with
reason ``financial_transaction``. A checkout that requires shopper login/OTP
is recorded as ``customer_login`` - the flow never enters codes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

from adapters.browser.controller import BrowserController, Locator, PageResult, UnsafeAction
from core.discovery.observation import SCHEMA_VERSION
from core.discovery.salla import ADD_TO_CART_LABELS, CHECKOUT_LABELS, is_product_link
from core.logging_utils import get_logger

log = get_logger("nittaq.flow")

ADD_TO_CART_SELECTORS = ("salla-add-product-button button", "[data-testid*='add-to-cart']", "form[action*='cart'] button[type='submit']")
CHECKOUT_SELECTORS = ("a[href*='/checkout']", "[data-testid*='checkout']")


def _same_host(a: str, b: str) -> bool:
    ha = (urlsplit(a).hostname or "").removeprefix("www.")
    hb = (urlsplit(b).hostname or "").removeprefix("www.")
    return ha == hb


class StorefrontFlow:
    def __init__(self, browser: BrowserController, product_url: str | None = None):
        self.b = browser
        self.product_url = product_url
        self.pages: list[dict[str, Any]] = []
        self.attempted: list[str] = []
        self.completed: list[str] = []
        self.blocked: dict[str, str] = {}
        self.notes: list[str] = []

    def _snapshot(self, step: str, res: PageResult) -> None:
        entry: dict[str, Any] = {"url": res.url, "step": step, "status": res.status, "page_load_id": self._load_id()}
        if res.error:
            entry["error"] = res.error
        if res.status == "ok":
            entry["html"] = self.b.html()
            dl = self.b.datalayer()
            entry["datalayer"] = dl
            entry["datalayer_read"] = True
        self.pages.append(entry)

    def _load_id(self) -> int:
        lid = getattr(self.b, "load_id", None)
        return lid if isinstance(lid, int) else len(self.pages)

    def _set_step(self, step: str) -> None:
        setter = getattr(self.b, "set_step", None)
        if callable(setter):
            setter(step)

    def _flush(self) -> None:
        f = getattr(self.b, "flush", None)
        if callable(f):
            f()

    def _open(self, url: str, step: str) -> bool:
        self.attempted.append(step)
        res = self.b.open(url, step)
        self._snapshot(step, res)
        if res.status == "ok":
            self.completed.append(step)
            return True
        self.blocked[step] = res.status
        return False

    def _click_any(self, labels: tuple[str, ...], selectors: tuple[str, ...], step: str) -> bool:
        for css in selectors:
            if self.b.click(Locator(css=css), step):
                return True
        for label in labels:
            if self.b.click(Locator(role="button", name=label), step) or self.b.click(Locator(role="link", name=label), step):
                return True
        return False

    def find_product(self, store_url: str) -> str | None:
        for href in self.b.links():
            if href.startswith("http") and _same_host(href, store_url) and is_product_link(href):
                return href
        return None

    def run(self, store_url: str) -> dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat()
        try:
            self._run(store_url)
        except UnsafeAction as exc:
            self.notes.append(f"stopped: {exc}")
            self.blocked.setdefault("begin_checkout", "financial_transaction")
        self._flush()
        for step in ("add_payment_info", "purchase"):
            self.blocked.setdefault(step, "financial_transaction")
        return {
            "schema_version": SCHEMA_VERSION,
            "store_url": store_url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "started_at": started,
            "adapter": self.b.name,
            "capabilities": self.b.capabilities().to_dict(),
            "pages": self.pages,
            "requests": self.b.network_log(),
            "flow": {"attempted": self.attempted, "completed": self.completed, "blocked": self.blocked},
            "notes": self.notes,
        }

    def _run(self, store_url: str) -> None:
        if not self._open(store_url, "home"):
            return
        product = self.product_url or self.find_product(store_url)
        if not product:
            self.blocked["view_item"] = "not_found"
            self.notes.append("no product link recognised on the home page")
            return
        self._flush()
        if not self._open(product, "view_item"):
            return

        self.attempted.append("add_to_cart")
        if self._click_any(ADD_TO_CART_LABELS, ADD_TO_CART_SELECTORS, "add_to_cart"):
            self.completed.append("add_to_cart")
            self.pages.append({"url": self.b.current_url(), "step": "add_to_cart", "status": "ok",
                               "page_load_id": self._load_id(), "datalayer": self.b.datalayer(), "datalayer_read": True})
        else:
            self.blocked["add_to_cart"] = "not_found"
            return

        self._flush()
        cart_url = urljoin(store_url, "/cart")
        if not self._open(cart_url, "view_cart"):
            return

        self.attempted.append("begin_checkout")
        before = self.b.current_url()
        if not self._click_any(CHECKOUT_LABELS, CHECKOUT_SELECTORS, "begin_checkout"):
            self.blocked["begin_checkout"] = "not_found"
            return
        blocker = getattr(self.b, "blocker", lambda: None)()
        if blocker in ("two_factor", "auth_required"):
            self.blocked["begin_checkout"] = "customer_login"
            self.notes.append("checkout requires shopper login; no code was entered")
        elif blocker == "captcha":
            self.blocked["begin_checkout"] = "captcha"
        else:
            self.completed.append("begin_checkout")
            self.pages.append({"url": self.b.current_url(), "step": "begin_checkout", "status": "ok",
                               "page_load_id": self._load_id(), "html": self.b.html(),
                               "datalayer": self.b.datalayer(), "datalayer_read": True,
                               "note": "navigated" if self.b.current_url() != before else "same_url"})
        self._set_step("begin_checkout")
