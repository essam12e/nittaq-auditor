# Snapchat Pixel (web)

| Field | Value |
|---|---|
| Sources | https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US · https://businesshelp.snapchat.com/s/article/event-mapping?language=en_US · https://developers.snap.com/api/marketing-api/Ads-API/audience-creation/website-events |
| Date checked | 2026-09-29 (web search excerpts; direct fetch blocked by sandbox policy) |
| Validator | `validators/snapchat/validator.py` (Snapchat rules only) |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `snap.event_names` | `snaptr('init', PIXEL_ID)` from `sc-static.net/scevent.min.js`; standard events `PAGE_VIEW`, `VIEW_CONTENT`, `ADD_CART`, `START_CHECKOUT`, `PURCHASE` | confirmed |
| `snap.purchase.params` | `PURCHASE`: `transaction_id` (unique), `item_ids`, `number_items` (mandatory per Snap), `price`, `currency` (recommended; with transaction_id needed for accurate ROAS) | confirmed |
| `snap.dedup.client_dedup_id` | `client_dedup_id` (UUID per event) when also sending via Conversions API | confirmed |

## Evidence
Hits go to `tr.snapchat.com` / `tr-shadow.snapchat.com`. The payload format is **not publicly specified**:
decoded best-effort, `UNPARSED` otherwise. CONNECTED_VERIFIED additionally requires confirmation from Snap's
test-events view (`dashboards.snapchat.test_events_confirmed`).

Detected: missing PURCHASE parameters, wrong currency, duplicate events per action, PURCHASE for the same
`transaction_id` re-fired on another page load (e.g. thank-you page reload).
