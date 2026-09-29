# Workflow: connect a service that is NOT_CONNECTED

Only after the user approved the `*.connect` proposal (state `EXECUTING`).

1. Tell the user which account will be connected and get an explicit confirmation of that exact account
   (property / container / pixel / ad account). If several exist, list them and ask; never guess.
2. Preferred path on Salla: the store's own marketing integration (Salla dashboard / Salla App Store app),
   e.g. the Google Tag Manager integration takes the Container ID (knowledge/salla/tracking.md). Avoid adding
   a second implementation next to an existing one (duplicate risk).
3. Navigate to the page where the ID is entered. Confirm URL and store name on the page.
4. `authorize --proposal P# --page-url <url> --resource-id <id being entered> --via salla --user-confirmed-target`.
5. Capture previous state (e.g. "field empty"), enter the ID, save.
6. `record-change` with the result and whether rollback is possible (usually: clear the field again).
7. `verify-begin`, collect a fresh storefront observation, `ingest --kind verify`.

Only the engine's verification decides whether the connection is verified. If hits do not appear, the
engine reports "configuration saved but not verified" — keep it that way.
