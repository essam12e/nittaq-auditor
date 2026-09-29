"""Static HTTP fallback (stdlib only, no JavaScript).

Used when no browser is available. It can reveal IDs present in markup and
product structured data, but it cannot observe runtime behaviour, so every
service it finds is capped at DETECTED by the validators. Its capabilities
are reported truthfully as javascript/network_capture/interaction = False.
"""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

from core.discovery.html_scanner import scan_html
from core.discovery.observation import SCHEMA_VERSION
from core.discovery.salla import is_product_link
from core.invocation import is_private_host

MAX_BYTES = 3_000_000
UA = "Mozilla/5.0 (compatible; nittaq-auditor/1.0; read-only audit)"


class _NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_local: bool):
        self.allow_local = allow_local

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        host = urlsplit(newurl).hostname or ""
        if not self.allow_local and _resolves_private(host):
            raise urllib.error.URLError("redirect to a private address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _resolves_private(host: str) -> bool:
    if is_private_host(host):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return any(is_private_host(str(info[4][0])) for info in infos)


class StaticHttpAdapter:
    name = "static-http"

    def __init__(self, timeout: float = 20.0, allow_local: bool = False):
        self.timeout = timeout
        self.allow_local = allow_local
        ctx = ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx), _NoPrivateRedirect(allow_local)
        )

    def fetch(self, url: str) -> dict[str, Any]:
        host = urlsplit(url).hostname or ""
        if not self.allow_local and _resolves_private(host):
            return {"url": url, "status": "blocked", "error": "private address refused"}
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(MAX_BYTES).decode(resp.headers.get_content_charset() or "utf-8", "replace")
                headers = {k: v for k, v in resp.headers.items() if k.lower() in ("server", "x-powered-by", "content-type")}
                return {"url": resp.geturl(), "status": "ok", "html": body, "headers": headers, "http_status": resp.status}
        except urllib.error.HTTPError as exc:
            return {"url": url, "status": "error", "error": f"HTTP {exc.code}", "http_status": exc.code}
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            status = "timeout" if "timed out" in str(reason) else "error"
            return {"url": url, "status": status, "error": str(reason)[:200]}

    def collect(self, store_url: str) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        home = self.fetch(store_url)
        home["step"] = "home"
        pages.append(home)
        completed = ["home"] if home["status"] == "ok" else []
        blocked: dict[str, str] = {}
        if home["status"] == "ok":
            links = [urljoin(home["url"], h) for h in scan_html(home["html"]).links]
            product = next((h for h in links if urlsplit(h).hostname == urlsplit(home["url"]).hostname and is_product_link(h)), None)
            if product:
                p = self.fetch(product)
                p["step"] = "view_item"
                pages.append(p)
                if p["status"] == "ok":
                    completed.append("view_item")
            else:
                blocked["view_item"] = "not_found"
        for step in ("add_to_cart", "view_cart", "begin_checkout", "add_payment_info", "purchase"):
            blocked.setdefault(step, "not_attempted" if step not in ("add_payment_info", "purchase") else "financial_transaction")
        for i, p in enumerate(pages):
            p["page_load_id"] = i
        return {
            "schema_version": SCHEMA_VERSION,
            "store_url": store_url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "adapter": self.name,
            "capabilities": {"javascript": False, "network_capture": False, "interaction": False},
            "pages": pages,
            "requests": [],
            "flow": {"attempted": [p["step"] for p in pages], "completed": completed, "blocked": blocked},
            "notes": ["static markup only: runtime behaviour not observed"],
        }
