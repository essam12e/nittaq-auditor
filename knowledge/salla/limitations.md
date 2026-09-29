# Salla-specific limitations

| Field | Value |
|---|---|
| Rule | `salla.checkout.customer_login` (unconfirmed), `salla.url.heuristics` (unconfirmed) |
| Sources | https://help.salla.sa/ · https://docs.salla.dev/1724667m0 (Cloud Mode, server-side events) |
| Date checked | 2026-09-29 |

- **Checkout may require shopper login with a one-time code.** The auditor never enters codes; the step is
  recorded as `customer_login` and post-cart events stay untested unless the user logs in themselves.
- **Purchase cannot be tested without a real order.** The auditor never creates orders or payments to test
  tracking. `purchase`, conversion value, and transaction IDs are reported as untested unless the user
  explicitly requested and understood a real test order.
- **Server-side events** (Meta Conversions API, TikTok Events API, Snapchat Conversions API, Salla Cloud Mode)
  are invisible to a browser; deduplication with them can only be checked for the browser half.
- **Storefront caching** may delay seeing integration changes; reload before verification.
- **Custom themes** may not follow the usual URL patterns or component names; the flow then reports
  `not_found` instead of guessing.
