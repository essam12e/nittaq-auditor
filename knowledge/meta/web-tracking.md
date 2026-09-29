# Meta Pixel (web)

| Field | Value |
|---|---|
| Sources | https://developers.facebook.com/docs/meta-pixel/reference/ · https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events |
| Date checked | 2026-09-29 (web search excerpts; direct fetch blocked by sandbox policy) |
| Validator | `validators/meta/validator.py` (Meta rules only) |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `meta.purchase.currency_value` | `Purchase` requires `currency` and `value` | confirmed |
| `meta.catalog.content_ids` | Advantage+ catalog ads need `contents` or `content_ids`; `content_type` = `product` / `product_group` matching the IDs | confirmed |
| `meta.dedup.event_id` | browser `eventID` must equal CAPI `event_id` and names must match; dedup window 48h; no dedup with a single source | confirmed |
| `meta.duplicate.browser` | one browser event per action | inference |

Standard commerce events: `ViewContent`, `AddToCart`, `InitiateCheckout`, `AddPaymentInfo`, `Purchase`
(plus `PageView`).

## Evidence
Hits: `https://www.facebook.com/tr/?id=<pixel>&ev=<Event>&cd[value]=…&cd[currency]=…&cd[content_ids]=[…]&eid=<eventID>`
(GET or POST). Loader: `connect.facebook.net/.../fbevents.js`, config `connect.facebook.net/signals/config/<pixel>`.

Server events (Conversions API, e.g. Salla's Meta CAPI) are not visible in the browser. Missing `eventID` is
only reported as high severity when the dashboard shows CAPI is active; otherwise it is informational.
