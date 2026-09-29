# Workflow: Google Merchant Center (separate, last)

States: `MERCHANT_APPROVAL_REQUIRED → MERCHANT_INSPECTING → MERCHANT_REPORT_READY → MERCHANT_WRITE_APPROVAL_REQUIRED → EXECUTING → VERIFYING → …`

1. After the tracking stage the engine shows the Merchant intro and asks whether to inspect. Pass the reply
   with `reply`. "Yes" allows **inspection only**. "No" ends the task without Merchant.
2. Inspection (agent browser, read-only) at merchants.google.com:
   - confirm the Merchant account matches the store domain; multiple accounts → `pause --kind multiple_accounts`;
   - read: account issues, website URL + claimed/verified status, data sources and their errors,
     product statuses and issues (sample if there are many), product link/price/availability;
   - open a few affected product pages on the storefront (price, availability, JSON-LD) for comparison.
3. Fill `dashboards.merchant` (+ storefront `pages[]` with HTML for compared products) and
   `ingest --kind merchant`.
4. The engine reports each issue with **where the fix belongs** (`fix_location`):
   price/availability mismatches usually originate in Salla product data or feed sync; landing-page issues in
   the store; identifiers in Salla product data; shipping/policy in Merchant Center.
5. Merchant changes need a **second** approval (`M1…`). Store-side fixes (Salla product data) are changes to
   Salla and are only done if the proposal covers them and the user approved.
6. High-risk: bulk product changes, deleting data sources/feeds, website/domain changes, account linking.
   These are destructive proposals (explicit `أؤكد M#`).
7. After changes: `verify-begin` → new Merchant inspection observation (fresh) → `ingest --kind verify`.
   Merchant re-review can take Google days; the engine will report `unable_to_verify` when statuses have not
   updated yet — say so, do not claim success.
