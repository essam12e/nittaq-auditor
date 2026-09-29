# Tracking integrations on Salla

| Field | Value |
|---|---|
| Sources | https://help.salla.sa/article/2103324124 (طريقة الربط مع Google Tag Manager), https://help.salla.sa/article/147991004 (أسئلة شائعة حول GTM), https://apps.salla.sa/en/app/347166518 (GTM app) |
| Date checked | 2026-09-29 (web search excerpts) |
| Rule | `gtm.salla.integration` (confirmed) |

## Confirmed
- GTM is connected on Salla by installing the Google Tag Manager integration/app and entering the
  **Container ID** (help.salla.sa steps: create account & container, copy code, install the app, enter the
  Container ID, activate).

## Not confirmed (verify live before any change)
- Exact dashboard menu labels for GA4 / Meta / TikTok / Snapchat integrations and whether each is native or
  provided by a Salla App Store app. Third-party apps (e.g. pixel tracker apps, server-side GTM apps) also
  inject tracking.
- Whether a native integration and a GTM tag can both fire the same event in a given store (common cause of
  duplicates — detect from evidence, don't assume).

## Practical guidance for fixes
1. Find which implementation sends each hit before changing anything: Salla integration, Salla app, GTM
   container, or theme/custom code.
2. Keep one implementation per platform+event. Prefer disabling the redundant one.
3. Any change in the Salla dashboard is a write → only after approval, with `authorize --via salla`.
