"""A local fake Salla-like storefront for integration tests (TEST FIXTURE ONLY).

It mimics the *shape* of a Salla store (Twilight script tag, salla-* web
component, /p<digits> product URL, /cart, OTP login on checkout) and sends
tracking requests in the wire formats the parser decodes. All third-party
hosts are intercepted by ``route_handler`` - nothing leaves the machine.
It is not a Salla store and proves nothing about real platforms.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

GA = "G-TEST123456"
PIXEL = "111222333444"

TRACKER_JS = """
<script>
window.dataLayer = window.dataLayer || [];
function nq_send(url, body){ try { navigator.sendBeacon ? fetch(url, {method: body ? 'POST' : 'GET', body: body || undefined, keepalive: true}) : 0; } catch(e){} }
function nq_ga(en, extra){
  var base = 'https://region1.google-analytics.com/g/collect?v=2&tid=%(ga)s' + (extra && extra.cu ? '&cu=' + extra.cu : '');
  var line = 'en=' + en + (extra && extra.body ? '&' + extra.body : '');
  nq_send(base, line);
}
function nq_fb(ev, cd){
  var q = 'https://www.facebook.com/tr/?id=%(px)s&ev=' + ev;
  for (var k in (cd||{})) q += '&cd[' + k + ']=' + encodeURIComponent(cd[k]);
  nq_send(q);
}
</script>
<script src="https://www.googletagmanager.com/gtag/js?id=%(ga)s"></script>
<script src="https://connect.facebook.net/signals/config/%(px)s"></script>
<script src="https://cdn.salla.network/js/twilight/latest/twilight.js"></script>
"""


def page(title: str, body: str, variant: str) -> str:
    return (
        "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><title>%s</title>" % title
        + TRACKER_JS % {"ga": GA, "px": PIXEL}
        + "</head><body>"
        + body
        + "<script>window.NQ_VARIANT=%s;</script>" % json.dumps(variant)
        + "</body></html>"
    )


def home(variant: str) -> str:
    return page(
        "المتجر",
        """
<h1>متجر تجريبي</h1>
<a href="/shirt/p1234567">قميص</a>
<script>nq_ga('page_view'); nq_fb('PageView');</script>
""",
        variant,
    )


def product(variant: str) -> str:
    currency = "" if variant == "broken" else "SAR"
    return page(
        "قميص",
        """
<h1>قميص</h1>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"قميص","sku":"SKU1",
 "offers":{"@type":"Offer","price":"100.00","priceCurrency":"SAR","availability":"https://schema.org/InStock"}}</script>
<salla-add-product-button><button type="button" id="atc">إضافة للسلة</button></salla-add-product-button>
<button type="button" id="buy">ادفع الآن</button>
<script>
var CUR = %(cur)s;
dataLayer.push({event: 'view_item', ecommerce: {currency: 'SAR', value: 100, items: [{item_id: 'SKU1', item_name: 'قميص', price: 100, quantity: 1}]}});
nq_ga('page_view');
nq_ga('view_item', {cu: CUR, body: 'epn.value=100&pr1=idSKU1~nmShirt~pr100~qt1'});
nq_fb('ViewContent', {content_ids: '["SKU1"]', content_type: 'product', value: 100, currency: 'SAR'});
document.getElementById('atc').addEventListener('click', function(){
  dataLayer.push({event: 'add_to_cart', ecommerce: {currency: 'SAR', value: 100, items: [{item_id: 'SKU1', price: 100, quantity: 1}]}});
  nq_ga('add_to_cart', {cu: CUR, body: 'epn.value=100&pr1=idSKU1~nmShirt~pr100~qt1'});
  nq_fb('AddToCart', {content_ids: '["SKU1"]', content_type: 'product', value: 100, currency: 'SAR'});
  if (window.NQ_VARIANT === 'broken') { nq_fb('AddToCart', {value: 100, currency: 'SAR'}); }
});
document.getElementById('buy').addEventListener('click', function(){ window.NQ_PAID = true; nq_ga('purchase'); });
</script>
""" % {"cur": json.dumps(currency)},
        variant,
    )


def cart(variant: str) -> str:
    return page(
        "السلة",
        """
<h1>السلة</h1>
<button type="button" id="co">إتمام الطلب</button>
<div id="login" style="display:none"><label>رمز التحقق<input autocomplete="one-time-code" name="otp"></label></div>
<script>
nq_ga('page_view');
nq_ga('view_cart', {cu: 'SAR', body: 'epn.value=100&pr1=idSKU1~nmShirt~pr100~qt1'});
document.getElementById('co').addEventListener('click', function(){
  nq_ga('begin_checkout', {cu: 'SAR', body: 'epn.value=100&pr1=idSKU1~nmShirt~pr100~qt1'});
  nq_fb('InitiateCheckout', {content_ids: '["SKU1"]', content_type: 'product', value: 100, currency: 'SAR'});
  document.getElementById('login').style.display = 'block';
});
</script>
""",
        variant,
    )


class _Handler(BaseHTTPRequestHandler):
    variant = "ok"

    def log_message(self, *args: Any) -> None:  # silence
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        routes = {"/": home, "/shirt/p1234567": product, "/cart": cart}
        fn = routes.get(path)
        if not fn:
            self.send_response(404)
            self.end_headers()
            return
        body = fn(self.variant).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeStore:
    def __init__(self, variant: str = "ok"):
        handler = type("H", (_Handler,), {"variant": variant})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def __enter__(self) -> FakeStore:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def route_handler(route: Any) -> None:
    """Keep everything local: third-party scripts get an empty body, hits get 204."""
    url = route.request.url
    if url.startswith("http://127.0.0.1"):
        route.continue_()
    elif url.endswith(".js") or "/gtag/js" in url or "/signals/config/" in url:
        route.fulfill(status=200, content_type="application/javascript", body="/* stub */")
    else:
        route.fulfill(status=204, body="")
