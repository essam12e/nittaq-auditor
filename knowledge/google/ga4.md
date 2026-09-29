# Google Analytics 4 — ecommerce requirements

| Field | Value |
|---|---|
| Sources | https://developers.google.com/analytics/devguides/collection/ga4/reference/events · https://developers.google.com/analytics/devguides/collection/ga4/set-up-ecommerce · https://developers.google.com/analytics/devguides/collection/ga4/ecommerce · https://support.google.com/analytics/answer/12313109 |
| Date checked | 2026-09-29 (web search excerpts of the official pages) |
| Validator | `validators/ga4/validator.py` |

## Rules

| Rule id | Requirement | Level | Confidence |
|---|---|---|---|
| `ga4.purchase.transaction_id_required` | `purchase` requires `transaction_id` | required | confirmed |
| `ga4.transaction_id.not_empty` | never send `transaction_id=""` (GA dedups all such purchases) | required | confirmed |
| `ga4.transaction_id.unique` | unique per order; static IDs undercount; GA4 web dedups same ID | required | confirmed |
| `ga4.currency.required_with_value` | `currency` (ISO 4217) required when `value` is set | conditional | confirmed |
| `ga4.items.id_or_name` | each item needs `item_id` or `item_name` | required | confirmed |
| `ga4.items.required` | ecommerce events carry `items` | required | **unconfirmed** → manual check |
| `ga4.currency.store_match` | currency matches the store's real currency (never forced to SAR) | recommended | derived |
| `ga4.duplicate.purchase` | one purchase per order per property | required | confirmed |
| `ga4.duplicate.page_view` | one page_view per page load per property | recommended | inference |

Events checked where the flow reached them: `view_item`, `add_to_cart`, `view_cart`, `begin_checkout`,
`add_payment_info`, `purchase`. Parameters are not blindly required on every event: `currency` is only
required with `value`; `transaction_id` only on `purchase`.

## How hits are decoded
gtag sends `…/g/collect?v=2&tid=G-…` with `en` (event name), `cu` (currency), `ep.*`/`epn.*` params,
`pr1..prN` items (`id`,`nm`,`pr`,`qt`,…), often batched one event per line in the POST body. This wire format
is not a public spec (`net.observed_endpoints`); the decoder only reports what it can parse.

## Fix guidance
- Fix at the source (Salla integration / GTM tag / theme code). Don't add a second GA4 implementation.
- `transaction_id` = the Salla order number/ID, dynamic per order.
- `value` numeric (period decimal), with `currency` = store currency.
