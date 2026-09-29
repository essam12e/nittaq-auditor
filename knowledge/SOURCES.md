# Documentation-source manifest

Generated from `knowledge/rules.json` by `scripts/check_knowledge.py` — do not edit by hand.

> On 2026-09-29 the build sandbox's network policy blocked direct fetches of developers.google.com, support.google.com, developers.facebook.com, ads.tiktok.com, businesshelp.snapchat.com and docs.salla.dev. Rules marked verification_method=web_search_excerpt were confirmed against excerpts of the listed official page returned by web search, not by reading the full page. Rules with confidence=unconfirmed are enforced only as manual-check advisories until a maintainer confirms them (see knowledge/REVIEW_PROCESS.md).

| Rule | Platform | Level | Confidence | Checked | Method | Sources |
|---|---|---|---|---|---|---|
| `ga4.purchase.transaction_id_required` | ga4 | required | confirmed | 2026-09-29 | web_search_excerpt | https://developers.google.com/analytics/devguides/collection/ga4/reference/events#purchase<br>https://developers.google.com/analytics/devguides/collection/ga4/set-up-ecommerce |
| `ga4.transaction_id.not_empty` | ga4 | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/analytics/answer/12313109 |
| `ga4.transaction_id.unique` | ga4 | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/analytics/answer/12313109 |
| `ga4.currency.required_with_value` | ga4 | conditional | confirmed | 2026-09-29 | web_search_excerpt | https://developers.google.com/analytics/devguides/collection/ga4/reference/events |
| `ga4.items.id_or_name` | ga4 | required | confirmed | 2026-09-29 | web_search_excerpt | https://developers.google.com/analytics/devguides/collection/ga4/reference/events |
| `ga4.items.required` | ga4 | required | unconfirmed | 2026-09-29 | web_search_excerpt | https://developers.google.com/analytics/devguides/collection/ga4/reference/events<br>https://developers.google.com/analytics/devguides/collection/ga4/ecommerce |
| `ga4.currency.store_match` | ga4 | recommended | confirmed | 2026-09-29 | derived_from_official_requirement | https://developers.google.com/analytics/devguides/collection/ga4/reference/events |
| `ga4.duplicate.purchase` | ga4 | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/analytics/answer/12313109 |
| `ga4.duplicate.page_view` | ga4 | recommended | unconfirmed | 2026-09-29 | engineering_inference | https://developers.google.com/analytics/devguides/collection/ga4/views |
| `gtm.container.duplicate` | gtm | required | unconfirmed | 2026-09-29 | engineering_inference | https://support.google.com/tagmanager/answer/6103696 |
| `gtm.publish.is_write` | gtm | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/tagmanager/answer/6107163<br>https://support.google.com/tagmanager/answer/6107056 |
| `gtm.salla.integration` | gtm | recommended | confirmed | 2026-09-29 | web_search_excerpt | https://help.salla.sa/article/2103324124<br>https://help.salla.sa/article/147991004<br>https://apps.salla.sa/en/app/347166518 |
| `ads.conversion.dynamic_value` | google_ads | recommended | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/google-ads/answer/6095947 |
| `ads.conversion.transaction_id` | google_ads | recommended | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/google-ads/answer/6386790 |
| `ads.conversion.send_to` | google_ads | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/google-ads/answer/6095947 |
| `ads.enhanced_conversions` | google_ads | recommended | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/google-ads/answer/13258081<br>https://support.google.com/google-ads/answer/13262500 |
| `meta.purchase.currency_value` | meta | required | confirmed | 2026-09-29 | web_search_excerpt | https://developers.facebook.com/docs/meta-pixel/reference/ |
| `meta.catalog.content_ids` | meta | conditional | confirmed | 2026-09-29 | web_search_excerpt | https://developers.facebook.com/docs/meta-pixel/reference/ |
| `meta.dedup.event_id` | meta | conditional | confirmed | 2026-09-29 | web_search_excerpt | https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events |
| `meta.duplicate.browser` | meta | recommended | unconfirmed | 2026-09-29 | engineering_inference | https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events |
| `tiktok.purchase.event_name` | tiktok | recommended | unconfirmed | 2026-09-29 | web_search_excerpt | https://ads.tiktok.com/help/article/standard-events-parameters |
| `tiktok.value_currency` | tiktok | conditional | confirmed | 2026-09-29 | web_search_excerpt | https://ads.tiktok.com/help/article/standard-events-parameters |
| `tiktok.content_id` | tiktok | conditional | unconfirmed | 2026-09-29 | web_search_excerpt | https://ads.tiktok.com/help/article/standard-events-parameters |
| `tiktok.dedup.event_id` | tiktok | conditional | unconfirmed | 2026-09-29 | web_search_excerpt | https://business-api.tiktok.com/portal/docs?id=1739585700402178 |
| `snap.purchase.params` | snapchat | required | confirmed | 2026-09-29 | web_search_excerpt | https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US<br>https://businesshelp.snapchat.com/s/article/event-mapping?language=en_US |
| `snap.dedup.client_dedup_id` | snapchat | conditional | confirmed | 2026-09-29 | web_search_excerpt | https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US |
| `snap.event_names` | snapchat | required | confirmed | 2026-09-29 | web_search_excerpt | https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US<br>https://developers.snap.com/api/marketing-api/Ads-API/audience-creation/website-events |
| `merchant.required_attributes` | merchant | required | confirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/merchants/answer/7052112 |
| `merchant.landing_page_match` | merchant | required | unconfirmed | 2026-09-29 | web_search_excerpt | https://support.google.com/merchants/answer/6098334<br>https://support.google.com/merchants/answer/7052112 |
| `salla.events.device_mode` | salla | observation | confirmed | 2026-09-29 | web_search_excerpt | https://docs.salla.dev/1804461m0<br>https://docs.salla.dev/1724504m0<br>https://docs.salla.dev/2007114m0 |
| `salla.twilight.sdk` | salla | observation | confirmed | 2026-09-29 | web_search_excerpt | https://docs.salla.dev/422610m0 |
| `salla.url.heuristics` | salla | observation | unconfirmed | 2026-09-29 | engineering_inference | https://docs.salla.dev/422610m0 |
| `salla.checkout.customer_login` | salla | observation | unconfirmed | 2026-09-29 | engineering_inference | https://help.salla.sa/ |
| `net.observed_endpoints` | network | observation | unconfirmed | 2026-09-29 | engineering_inference | https://developers.facebook.com/docs/meta-pixel/<br>https://support.google.com/google-ads/answer/6095947<br>https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US |

## All official sources

- https://ads.tiktok.com/help/article/standard-events-parameters
- https://apps.salla.sa/en/app/347166518
- https://business-api.tiktok.com/portal/docs?id=1739585700402178
- https://businesshelp.snapchat.com/s/article/event-mapping?language=en_US
- https://businesshelp.snapchat.com/s/article/pixel-direct-implementation?language=en_US
- https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events
- https://developers.facebook.com/docs/meta-pixel/
- https://developers.facebook.com/docs/meta-pixel/reference/
- https://developers.google.com/analytics/devguides/collection/ga4/ecommerce
- https://developers.google.com/analytics/devguides/collection/ga4/reference/events
- https://developers.google.com/analytics/devguides/collection/ga4/reference/events#purchase
- https://developers.google.com/analytics/devguides/collection/ga4/set-up-ecommerce
- https://developers.google.com/analytics/devguides/collection/ga4/views
- https://developers.snap.com/api/marketing-api/Ads-API/audience-creation/website-events
- https://docs.salla.dev/1724504m0
- https://docs.salla.dev/1804461m0
- https://docs.salla.dev/2007114m0
- https://docs.salla.dev/422610m0
- https://help.salla.sa/
- https://help.salla.sa/article/147991004
- https://help.salla.sa/article/2103324124
- https://support.google.com/analytics/answer/12313109
- https://support.google.com/google-ads/answer/13258081
- https://support.google.com/google-ads/answer/13262500
- https://support.google.com/google-ads/answer/6095947
- https://support.google.com/google-ads/answer/6386790
- https://support.google.com/merchants/answer/6098334
- https://support.google.com/merchants/answer/7052112
- https://support.google.com/tagmanager/answer/6103696
- https://support.google.com/tagmanager/answer/6107056
- https://support.google.com/tagmanager/answer/6107163
