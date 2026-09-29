# Workflow: verification and re-audit

States: `EXECUTING → VERIFYING → RE_AUDITING → MERCHANT_APPROVAL_REQUIRED | COMPLETED | PARTIALLY_COMPLETED`

1. `verify-begin --session S`. The engine lists approved proposals that were not executed.
2. Wait for platform changes to propagate if needed (GTM publish is immediate for new page loads; some
   Salla integration changes may need a cache refresh — reload the store).
3. Collect a **new** observation. Its `collected_at` must be later than the last change or the engine
   rejects it as stale.
4. `ingest --session S --file new.json --kind verify`.

The engine marks each change:

| result | meaning |
|---|---|
| `verified` | service CONNECTED_VERIFIED and targeted findings gone |
| `partially_verified` | targeted findings gone, but not every aspect could be tested |
| `failed` | change failed, or targeted findings remain, or new issues appeared |
| `unable_to_verify` | evidence insufficient (no browser, login wall, undecodable hits…) |

Then the full re-audit report is shown. Never summarise a non-`verified` result as success. Purchase-only
behaviour (conversion value, transaction_id) stays untested unless a real order was explicitly authorised.
