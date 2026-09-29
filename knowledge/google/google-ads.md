# Google Ads conversion tracking

| Field | Value |
|---|---|
| Sources | https://support.google.com/google-ads/answer/6095947 (transaction-specific values) · https://support.google.com/google-ads/answer/6386790 (transaction ID) · https://support.google.com/google-ads/answer/13258081 · https://support.google.com/google-ads/answer/13262500 (enhanced conversions) |
| Date checked | 2026-09-29 (web search excerpts) |
| Validator | `validators/google_ads/validator.py` |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `ads.conversion.send_to` | `gtag('event','conversion',{send_to:'AW-ID/LABEL', …})` | confirmed |
| `ads.conversion.dynamic_value` | pass order value (number, period decimal) + ISO 4217 currency at runtime | confirmed |
| `ads.conversion.transaction_id` | unique transaction ID minimises duplicate conversions | confirmed |
| `ads.enhanced_conversions` | user-provided data via Google tag/GTM; unified setting from April 2026 | confirmed (info only) |

## Evidence
Conversion requests: `googleads.g.doubleclick.net/pagead/viewthroughconversion/<id>/`,
`www.google.com/pagead/1p-conversion/<id>/` (a single gtag conversion normally produces both — not a
duplicate), with `label`, `value`, `currency_code`, `oid` (transaction id).

A conversion action existing in the Google Ads UI is **not** proof. Without a completed order the conversion
itself cannot be observed; the service is then PARTIALLY_VERIFIED at best.

Detected: duplicate conversions, missing/static value (0/1 suspicious, same value for different order totals,
"static" value setting in dashboard), missing transaction id, wrong currency, value ≠ GA4 purchase value in the
same page load, several primary purchase conversion actions or several AW targets per purchase.
