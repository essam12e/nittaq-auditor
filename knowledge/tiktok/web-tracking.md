# TikTok Pixel (web)

| Field | Value |
|---|---|
| Sources | https://ads.tiktok.com/help/article/standard-events-parameters · https://business-api.tiktok.com/portal/docs?id=1739585700402178 |
| Date checked | 2026-09-29 (web search excerpts; direct fetch blocked by sandbox policy) |
| Validator | `validators/tiktok/validator.py` (TikTok rules only — not Meta's) |

## Rules
| Rule id | Requirement | Confidence |
|---|---|---|
| `tiktok.value_currency` | `value` required for ROAS / value-based optimisation; `currency` required for ROAS | confirmed |
| `tiktok.purchase.event_name` | current purchase event is `Purchase`; `CompletePayment` renamed to `Purchase`, `PlaceAnOrder` soft-deprecated | **unconfirmed** (partly non-official excerpts) |
| `tiktok.content_id` | commerce events include `content_id` / `content_type` for catalog matching | **unconfirmed** |
| `tiktok.dedup.event_id` | shared `event_id` deduplicates Pixel + Events API | **unconfirmed** |

Legacy names are accepted as purchase events and flagged only as a low-severity manual check.

## Evidence
Loader: `analytics.tiktok.com/i18n/pixel/events.js?sdkid=<code>`. Hits: POST to `analytics.tiktok.com/api/…`
with a JSON body. The payload format is **not publicly specified**: decoding is best-effort, undecodable hits are
reported as `UNPARSED` → CONNECTED_UNVERIFIED. Even well-decoded hits need confirmation in TikTok Events
Manager "Test Events" (`dashboards.tiktok.test_events_confirmed`) before the engine reports CONNECTED_VERIFIED.
