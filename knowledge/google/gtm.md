# Google Tag Manager

| Field | Value |
|---|---|
| Sources | https://support.google.com/tagmanager/answer/6107163 · https://support.google.com/tagmanager/answer/6107056 · https://support.google.com/tagmanager/answer/6103696 · https://help.salla.sa/article/2103324124 |
| Date checked | 2026-09-29 (web search excerpts) |
| Validator | `validators/gtm/validator.py` |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `gtm.publish.is_write` | Submit → "Publish and Create Version" makes workspace changes live → write, needs approval. Preview mode (Tag Assistant) tests the draft. | confirmed |
| `gtm.container.duplicate` | a container should load once per page | inference |
| `gtm.salla.integration` | Salla connects GTM via the integration + Container ID | confirmed |

## What "working" means here
GTM sends no hits itself. The auditor checks: `gtm.js?id=GTM-…` requested at runtime; the container executed
(`gtm.js`/`gtm.load` in `dataLayer`); ecommerce objects exist in `dataLayer` for GTM tags to use; and — if the
dashboard was readable — the container id matches the store, no unpublished changes, no duplicate tags
(same type + id + event), and conversion tags don't fire on "All Pages".
Without dashboard access GTM can reach at most PARTIALLY_VERIFIED.

## Publishing
Never during audit. After approval: list exactly what will be published (tags/triggers/variables changed),
confirm the container id on the page, publish, record the new version number, then verify on the storefront.
Rollback: republishing the previous version is possible in GTM (Versions).
