# Salla ecommerce events (app event stream)

| Field | Value |
|---|---|
| Sources | https://docs.salla.dev/1804461m0 (Cart & Checkout events), https://docs.salla.dev/1724504m0 (Device Mode), https://docs.salla.dev/1724667m0 (Cloud Mode), https://docs.salla.dev/2007114m0 (Custom events) |
| Date checked | 2026-09-29 (web search excerpts) |
| Rule | `salla.events.device_mode` (confirmed) |

Salla exposes ecommerce events to **apps**:

- **Device Mode** — a tracker script injected into the storefront (App Snippet) receives events in the
  shopper's browser.
- **Cloud Mode** — events are delivered server-side to the app.

Documented events include: `Product Viewed`, `Product Added`, `Product Removed`, `Cart Viewed`,
`Cart Updated`, `Checkout Started`, `Checkout Step Viewed`, `Checkout Step Completed`,
`Payment Info Entered`, `Order Completed`. Custom events: `Salla.analytics.track(eventName, properties)`.

## How the auditor uses this
These are **not** GA4/Meta/TikTok/Snap hits. They explain where platform events can come from: a Salla
integration or app may translate `Order Completed` into GA4 `purchase`, Meta `Purchase`, etc. When a
platform event is duplicated, one likely cause is a Salla integration *and* a GTM tag / theme snippet both
translating the same Salla event. The auditor reports this as evidence + inference, never removes anything.

Mapping used only for funnel labelling (`core/discovery/salla.py:SALLA_EVENTS_TO_FUNNEL`):

| Salla event | Funnel step |
|---|---|
| Product Viewed | view_item |
| Product Added | add_to_cart |
| Cart Viewed | view_cart |
| Checkout Started | begin_checkout |
| Payment Info Entered | add_payment_info |
| Order Completed | purchase |

Payload field names were not fully visible in the sources and are **not** relied upon.
