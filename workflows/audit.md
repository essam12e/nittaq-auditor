# Workflow: audit (read-only)

States: `IDLE → WAITING_FOR_STORE → DISCOVERING → AUDITING → REPORT_READY → WAITING_FOR_APPROVAL | MERCHANT_APPROVAL_REQUIRED`

1. `start --text "<user message>"`. If no URL, show the welcome and wait (`reply` with the URL).
2. `detect --agent-browser <your real tool or none>`.
3. Storefront evidence (read-only), in this order of preference:
   - agent browser: `plan --session S --agent-browser <tool>` → perform the steps → fill the skeleton → `ingest`;
   - in-process Playwright: `collect --session S`;
   - static fallback: `collect --session S --adapter static` (can only reach DETECTED).
4. Safe flow: home → one product → add to cart once → cart → click checkout once. Stop at login/OTP/CAPTCHA
   (record `flow.blocked`). Never click pay / confirm-order. `add_payment_info` and `purchase` stay blocked with
   `financial_transaction` unless the user explicitly requested and understood a real order.
5. Optional dashboards (agent browser only, read-only): GA4, GTM, Google Ads, Meta Events Manager, TikTok and
   Snapchat Events Managers. Record facts under `dashboards.<service>`. Stop on login/2FA/CAPTCHA
   (`pause`), on multiple candidate accounts (`pause --kind multiple_accounts`), on unexpected UI (`fail`).
6. The engine returns the Arabic report + proposals. Show it verbatim.

Processing order inside the engine: GA4, GTM, Google Ads, Meta, TikTok, Snapchat, cross-platform duplicates.
Merchant Center is never part of this pass.

What the report guarantees:
- each service has one explicit status (never collapsed to "connected");
- every finding says whether it is an observed fact, an inference, unverified, or needs manual checking;
- untested steps are listed; "no problems" is only ever said as "within the checks we could run";
- the footer states that nothing was changed.
