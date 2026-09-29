# Salla storefront

| Field | Value |
|---|---|
| Sources | https://docs.salla.dev/422610m0 (Twilight SDK overview) |
| Date checked | 2026-09-29 (web search excerpts; direct fetch blocked by sandbox policy) |
| Rules | `salla.twilight.sdk` (confirmed), `salla.url.heuristics` (unconfirmed) |
| Used by | `core/discovery/salla.py`, `core/discovery/html_scanner.py`, `adapters/browser/flow.py` |

## Confirmed
- Salla themes are built on the **Twilight** engine; the JS SDK is served from
  `cdn.salla.network/js/twilight/...` and exposes `window.salla` (`salla.init()`, config, events).
- Salla ships web components (`<salla-...>` custom elements) used by themes.

## Used as hints only (not documented by Salla)
- Product URLs commonly end with `/p<digits>`; the cart is at `/cart`.
- The add-to-cart control is usually inside `<salla-add-product-button>`.
- The storefront flow labels steps from what it actually did; URL patterns never override that.

## Recognising a Salla store
Strong markers: `cdn.salla.network`, Twilight script, `<salla-*>` components, `salla.<api>` usage, Salla
headers. A weak marker alone (e.g. a `cdn.salla.sa` image) does not classify a store as Salla. If a store is
not recognised as Salla the report says so and continues with generic checks.
