"""Builders for synthetic observations (TEST FIXTURES ONLY).

Hits are produced in the same wire formats the parser decodes, so scenario
tests exercise parser + validators together.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

STORE = "https://store.example.com/"
GA = "G-ABC1234567"
AW = "AW-123456789"
PIXEL = "1234567890"
TT = "CABCDEFGHIJ1234567"
SNAP = "11111111-2222-3333-4444-555555555555"

SALLA_HOME = (
    "<script src='https://cdn.salla.network/js/twilight/latest/twilight.js'></script>"
    "<script type='application/ld+json'>{\"@type\":\"Product\",\"offers\":{\"price\":100,\"priceCurrency\":\"SAR\"}}</script>"
)

STEP_LOAD = {"home": 0, "view_item": 1, "add_to_cart": 1, "view_cart": 2, "begin_checkout": 3, "purchase": 4}


class Obs:
    def __init__(self, behavioral: bool = True, adapter: str = "test", store: str = STORE):
        self.d: dict[str, Any] = {
            "schema_version": 1,
            "store_url": store,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "adapter": adapter,
            "capabilities": {"javascript": behavioral, "network_capture": behavioral, "interaction": behavioral},
            "pages": [],
            "requests": [],
            "captured_events": [],
            "flow": {"attempted": [], "completed": [], "blocked": {}},
            "dashboards": {},
        }

    # ------------------------------------------------------------ pages / flow
    def page(self, step: str, html: str = "", status: str = "ok", url: str | None = None, datalayer: list | None = None) -> Obs:
        u = url or {"home": STORE, "view_item": STORE + "shirt/p1234567", "add_to_cart": STORE + "shirt/p1234567",
                    "view_cart": STORE + "cart", "begin_checkout": STORE + "checkout", "purchase": STORE + "thanks"}.get(step, STORE + step)
        self.d["pages"].append({"url": u, "step": step, "status": status, "page_load_id": STEP_LOAD.get(step, 9),
                                "html": html, "datalayer": datalayer or []})
        self.d["flow"]["attempted"].append(step)
        if status == "ok":
            self.d["flow"]["completed"].append(step)
        return self

    def funnel(self, *steps: str, html_home: str = SALLA_HOME) -> Obs:
        for s in steps:
            self.page(s, html_home if s == "home" else "")
        return self

    def blocked(self, step: str, reason: str) -> Obs:
        self.d["flow"]["blocked"][step] = reason
        return self

    def req(self, url: str, step: str, body: str | None = None, load: int | None = None) -> Obs:
        self.d["requests"].append({"url": url, "post_data": body, "step": step,
                                   "page_load_id": STEP_LOAD.get(step, 9) if load is None else load,
                                   "page_url": STORE})
        return self

    def dashboard(self, service: str, **data: Any) -> Obs:
        self.d["dashboards"][service] = data
        return self

    def facts(self, **facts: Any) -> Obs:
        self.d["store_facts"] = facts
        return self

    def build(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.d))

    # ------------------------------------------------------------ platforms
    def gtag_loader(self, tid: str = GA, step: str = "home") -> Obs:
        return self.req(f"https://www.googletagmanager.com/gtag/js?id={tid}", step)

    def gtm(self, cid: str = "GTM-ABCD123", step: str = "home", load: int | None = None) -> Obs:
        return self.req(f"https://www.googletagmanager.com/gtm.js?id={cid}", step, load=load)

    def ga4(self, en: str, step: str, tid: str = GA, currency: str | None = "SAR", value: Any = 100,
            items: str | None = "idSKU1~nmShirt~pr100~qt1", tx: str | None = None, extra: str = "", load: int | None = None) -> Obs:
        q = f"https://region1.google-analytics.com/g/collect?v=2&tid={tid}" + (f"&cu={currency}" if currency else "")
        parts = [f"en={en}"]
        if value is not None:
            parts.append(f"epn.value={value}")
        if items:
            parts.append(f"pr1={items}")
        if tx is not None:
            parts.append(f"ep.transaction_id={tx}")
        if extra:
            parts.append(extra)
        return self.req(q, step, "&".join(parts), load=load)

    def ga4_pageview(self, step: str = "home", tid: str = GA, load: int | None = None) -> Obs:
        return self.req(f"https://region1.google-analytics.com/g/collect?v=2&tid={tid}&en=page_view", step, load=load)

    def ads(self, step: str = "purchase", aw: str = AW, label: str | None = "AbCdEf", value: Any = 250.5,
            currency: str | None = "SAR", oid: str | None = "ORDER1", endpoint: str = "viewthroughconversion",
            load: int | None = None) -> Obs:
        host = "googleads.g.doubleclick.net" if endpoint == "viewthroughconversion" else "www.google.com"
        path = f"/pagead/{endpoint}/{aw.removeprefix('AW-')}/"
        q = []
        if label:
            q.append(f"label={label}")
        if value is not None:
            q.append(f"value={value}")
        if currency:
            q.append(f"currency_code={currency}")
        if oid:
            q.append(f"oid={oid}")
        return self.req(f"https://{host}{path}?" + "&".join(q), step, load=load)

    def meta(self, ev: str, step: str, pixel: str = PIXEL, load: int | None = None, **cd: Any) -> Obs:
        eid = cd.pop("eid", None)
        q = f"https://www.facebook.com/tr/?id={pixel}&ev={ev}"
        for k, v in cd.items():
            q += f"&cd[{k}]={quote(json.dumps(v) if isinstance(v, list) else str(v))}"
        if eid:
            q += f"&eid={eid}"
        return self.req(q, step, load=load)

    def tiktok(self, event: str, step: str, code: str = TT, load: int | None = None, **props: Any) -> Obs:
        eid = props.pop("event_id", None)
        body = {"event": event, "context": {"pixel": {"code": code}}, "properties": props}
        if eid:
            body["event_id"] = eid
        return self.req("https://analytics.tiktok.com/api/v2/pixel", step, json.dumps(body), load=load)

    def snap(self, ev: str, step: str, pid: str = SNAP, load: int | None = None, **params: Any) -> Obs:
        body = {"pid": pid, "ev": ev, **params}
        return self.req("https://tr.snapchat.com/p", step, json.dumps(body), load=load)


def full_ga4(o: Obs, **purchase_kw: Any) -> Obs:
    o.gtag_loader().ga4_pageview("home").ga4("view_item", "view_item").ga4("add_to_cart", "add_to_cart")
    if purchase_kw.pop("with_purchase", False):
        o.ga4("purchase", "purchase", **purchase_kw)
    return o


def healthy_funnel(with_purchase: bool = False) -> Obs:
    o = Obs().funnel("home", "view_item", "add_to_cart")
    if with_purchase:
        o.page("purchase")
    return o
