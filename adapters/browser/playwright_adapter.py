"""In-process browser adapter using Playwright (optional dependency).

Records every outgoing request (URL, method, body) with the flow step that
was active when it was sent, reads ``window.dataLayer`` per page, and
detects *visible* security challenges. It never fills inputs and refuses to
click payment/order controls (SafetyPolicy).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.browser.controller import (
    BrowserController,
    BrowserUnavailable,
    Capabilities,
    Locator,
    PageResult,
    SafetyPolicy,
)
from core.logging_utils import get_logger

log = get_logger("nittaq.playwright")

CHROMIUM_CANDIDATES = (
    os.environ.get("NITTAQ_CHROMIUM_PATH", ""),
    "/opt/pw-browsers/chromium",
)

_DATALAYER_JS = """
() => {
  const seen = new WeakSet();
  const clean = (v, d) => {
    if (d > 8) return null;
    if (v === null || typeof v !== 'object') return (typeof v === 'function') ? undefined : v;
    if (seen.has(v)) return null;
    seen.add(v);
    if (Array.isArray(v)) return v.map(x => clean(x, d + 1));
    const o = {};
    for (const k of Object.keys(v)) { const c = clean(v[k], d + 1); if (c !== undefined) o[k] = c; }
    return o;
  };
  try {
    const dl = window.dataLayer;
    if (!Array.isArray(dl)) return {present: false, entries: []};
    return {present: true, entries: dl.map(e => clean(e, 0)).filter(e => e && typeof e === 'object' && !Array.isArray(e))};
  } catch (e) { return {present: false, entries: [], error: String(e)}; }
}
"""

_VISIBLE_BLOCKERS = (
    ("two_factor", "input[autocomplete='one-time-code']:visible, input[name*='otp' i]:visible"),
    ("auth_required", "input[type='password']:visible"),
    ("captcha", "iframe[src*='recaptcha/api2/bframe']:visible, iframe[src*='hcaptcha.com']:visible, iframe[src*='challenges.cloudflare.com']:visible"),
)


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class PlaywrightAdapter(BrowserController):
    name = "playwright"

    def __init__(
        self,
        headless: bool = True,
        route_handler: Callable[[Any], None] | None = None,
        nav_timeout_ms: int = 30_000,
        user_agent: str | None = None,
    ):
        """``route_handler`` exists ONLY for automated tests (fixture stores)."""
        if not playwright_available():
            raise BrowserUnavailable("playwright python package is not installed")
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = None
        errors = []
        for path in (None, *[c for c in CHROMIUM_CANDIDATES if c and Path(c).exists()]):
            try:
                self._browser = self._pw.chromium.launch(headless=headless, executable_path=path) if path else self._pw.chromium.launch(headless=headless)
                break
            except Exception as exc:  # noqa: BLE001 - try next candidate
                errors.append(str(exc).splitlines()[0])
        if self._browser is None:
            self._pw.stop()
            raise BrowserUnavailable("no launchable chromium: " + " | ".join(errors))
        self._ctx = self._browser.new_context(locale="ar-SA", user_agent=user_agent) if user_agent else self._browser.new_context(locale="ar-SA")
        if route_handler:
            self._ctx.route("**/*", route_handler)
        self._page = self._ctx.new_page()
        self._page.set_default_navigation_timeout(nav_timeout_ms)
        self._requests: list[dict[str, Any]] = []
        self._step = "home"
        self._load_id = -1
        self._t0 = time.time()
        self._page.on("request", self._on_request)
        self._page.on("framenavigated", self._on_nav)

    # ---------------------------------------------------------------- events
    def _on_nav(self, frame: Any) -> None:
        if frame == self._page.main_frame:
            self._load_id += 1

    def _on_request(self, req: Any) -> None:
        try:
            body = req.post_data
        except Exception:  # noqa: BLE001 - binary bodies
            body = None
        self._requests.append(
            {
                "url": req.url,
                "method": req.method,
                "post_data": body,
                "resource_type": req.resource_type,
                "page_url": self._page.url,
                "step": self._step,
                "page_load_id": max(self._load_id, 0),
                "t": round(time.time() - self._t0, 3),
            }
        )

    # ---------------------------------------------------------------- API
    def capabilities(self) -> Capabilities:
        return Capabilities(javascript=True, network_capture=True, interaction=True)

    @property
    def load_id(self) -> int:
        return max(self._load_id, 0)

    def set_step(self, step: str) -> None:
        self._step = step

    def open(self, url: str, step: str) -> PageResult:
        self._step = step
        try:
            resp = self._page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).splitlines()[0]
            return PageResult(url, "timeout" if "Timeout" in msg else "error", error=msg)
        self.wait_idle()
        blocker = self.blocker()
        status = resp.status if resp else None
        if blocker:
            return PageResult(self._page.url, blocker, status)
        if status and status >= 400:
            return PageResult(self._page.url, "error", status, error=f"HTTP {status}")
        return PageResult(self._page.url, "ok", status)

    def blocker(self) -> str | None:
        for kind, sel in _VISIBLE_BLOCKERS:
            try:
                if self._page.locator(sel).count() > 0:
                    return kind
            except Exception:  # noqa: BLE001
                continue
        return SafetyPolicy.classify_blocker(self.html(), self._page.url)

    def html(self) -> str:
        try:
            return self._page.content()
        except Exception:  # noqa: BLE001
            return ""

    def current_url(self) -> str:
        return self._page.url

    def links(self) -> list[str]:
        try:
            return self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        except Exception:  # noqa: BLE001
            return []

    def click(self, locator: Locator, step: str) -> bool:
        SafetyPolicy.check_click(locator)
        if locator.css:
            loc = self._page.locator(locator.css)
        elif locator.role and locator.name:
            loc = self._page.get_by_role(locator.role, name=locator.name)  # type: ignore[arg-type]
        elif locator.name:
            loc = self._page.get_by_text(locator.name, exact=False)
        else:
            return False
        try:
            count = loc.count()
        except Exception:  # noqa: BLE001
            return False
        for i in range(count):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                SafetyPolicy.check_click(locator, el.inner_text(timeout=2000))
                self._step = step
                el.click(timeout=5000)
                self.wait_idle()
                return True
            except Exception as exc:  # noqa: BLE001
                if exc.__class__.__name__ == "UnsafeAction":
                    raise
                log.info("click failed on %s: %s", locator.describe(), str(exc).splitlines()[0])
        return False

    def datalayer(self) -> list[dict[str, Any]]:
        try:
            res = self._page.evaluate(_DATALAYER_JS)
        except Exception:  # noqa: BLE001
            return []
        return list(res.get("entries") or [])

    def datalayer_present(self) -> bool:
        try:
            return bool(self._page.evaluate(_DATALAYER_JS).get("present"))
        except Exception:  # noqa: BLE001
            return False

    def network_log(self) -> list[dict[str, Any]]:
        return list(self._requests)

    def wait_idle(self, ms: int = 2500) -> None:
        try:
            self._page.wait_for_load_state("networkidle", timeout=ms + 5000)
        except Exception:  # noqa: BLE001 - long-polling pages never go idle
            pass
        self._page.wait_for_timeout(ms)

    def flush(self) -> None:
        """Ask tags to flush batched hits (gtag batches until page hide)."""
        try:
            self._page.evaluate(
                "() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('pagehide')); }"
            )
        except Exception:  # noqa: BLE001
            pass
        self._page.wait_for_timeout(1500)

    def close(self) -> None:
        closers = [self._ctx.close, self._pw.stop]
        if self._browser is not None:
            closers.insert(1, self._browser.close)
        for fn in closers:
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
