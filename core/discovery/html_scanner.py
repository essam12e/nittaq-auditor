"""Static markup scanning.

Finding an ID in markup only proves that *something references* the ID. It is
never treated as proof that tracking works (see validators: static-only
evidence caps a service at DETECTED).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from core.discovery.network_parser import detect_loader

_ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gtm", re.compile(r"\b(GTM-[A-Z0-9]{4,10})\b")),
    ("ga4", re.compile(r"\b(G-[A-Z0-9]{6,12})\b")),
    ("google_ads", re.compile(r"\b(AW-\d{6,12})\b")),
    ("meta", re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{8,20})['\"]")),
    ("tiktok", re.compile(r"ttq\.load\(\s*['\"]([A-Z0-9]{10,30})['\"]")),
    ("snapchat", re.compile(r"snaptr\(\s*['\"]init['\"]\s*,\s*['\"]([a-f0-9-]{20,40})['\"]", re.IGNORECASE)),
)


@dataclass
class HtmlScan:
    script_srcs: list[str] = field(default_factory=list)
    ids: dict[str, list[str]] = field(default_factory=dict)  # platform -> ids
    loaders: list[tuple[str, str | None]] = field(default_factory=list)
    json_ld_products: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    salla_signals: list[str] = field(default_factory=list)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.script_srcs: list[str] = []
        self.inline_scripts: list[str] = []
        self.json_ld: list[str] = []
        self.links: list[str] = []
        self.tags_seen: set[str] = set()
        self._in_script: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        self.tags_seen.add(tag)
        if tag == "script":
            if a.get("src"):
                self.script_srcs.append(a["src"])
            self._in_script = a.get("type", "").lower() or "js"
            self._buf = []
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("iframe",) and a.get("src"):
            self.script_srcs.append(a["src"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script is not None:
            content = "".join(self._buf)
            if self._in_script == "application/ld+json":
                self.json_ld.append(content)
            else:
                self.inline_scripts.append(content)
            self._in_script = None

    def handle_data(self, data: str) -> None:
        if self._in_script is not None:
            self._buf.append(data)


def _products_from_ld(obj: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(obj, list):
        for o in obj:
            _products_from_ld(o, out)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types:
            offers = obj.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
            out.append(
                {
                    "name": obj.get("name"),
                    "sku": obj.get("sku"),
                    "gtin": obj.get("gtin") or obj.get("gtin13") or obj.get("gtin12") or obj.get("gtin8"),
                    "mpn": obj.get("mpn"),
                    "offers": [
                        {
                            "price": o.get("price"),
                            "priceCurrency": o.get("priceCurrency"),
                            "availability": o.get("availability"),
                        }
                        for o in offer_list
                        if isinstance(o, dict)
                    ],
                }
            )
        for key in ("@graph", "mainEntity"):
            if key in obj:
                _products_from_ld(obj[key], out)


SALLA_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cdn.salla.network", re.compile(r"cdn\.salla\.network", re.IGNORECASE)),
    ("cdn.salla.sa", re.compile(r"cdn\.salla\.sa", re.IGNORECASE)),
    ("twilight_sdk", re.compile(r"twilight(\.min)?\.js", re.IGNORECASE)),
    ("salla_web_components", re.compile(r"<salla-[a-z-]+", re.IGNORECASE)),
    ("salla_js_global", re.compile(r"\bsalla\.(init|config|event|cart|analytics)\b")),
)


def scan_html(html: str) -> HtmlScan:
    c = _Collector()
    try:
        c.feed(html)
        c.close()
    except Exception:  # noqa: BLE001 - malformed HTML: fall back to regex-only scanning
        pass
    scan = HtmlScan(script_srcs=c.script_srcs, links=c.links)
    for src in c.script_srcs:
        scan.loaders.extend(detect_loader(src if "//" in src else "https://invalid" + src))
    haystack = "\n".join(c.inline_scripts) + "\n" + "\n".join(c.script_srcs)
    for platform, pat in _ID_PATTERNS:
        found = sorted({m.group(1).upper() if platform in ("gtm", "ga4", "google_ads") else m.group(1) for m in pat.finditer(haystack)})
        if found:
            scan.ids[platform] = found
    for raw in c.json_ld:
        try:
            _products_from_ld(json.loads(raw), scan.json_ld_products)
        except ValueError:
            continue
    for name, pat in SALLA_MARKERS:
        if pat.search(html):
            scan.salla_signals.append(name)
    return scan
