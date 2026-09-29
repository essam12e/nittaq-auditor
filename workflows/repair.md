# Workflow: repair approved issues

Precondition: state `EXECUTING`, proposal approved (and `أؤكد P#` for destructive ones).

For each approved proposal, one at a time:

1. Read the relevant knowledge file (`knowledge/google/ga4.md`, `gtm.md`, `google-ads.md`,
   `meta/web-tracking.md`, `tiktok/web-tracking.md`, `snapchat/web-tracking.md`).
2. Locate the **source** of the problem first (Salla integration, GTM tag, theme code, app). Fix at the source;
   don't add a compensating second implementation.
3. Navigate, confirm page + account, `authorize` (exit 3 → stop and show the text).
4. Capture previous state (tag config, trigger, setting values).
5. Change only what the proposal describes. For duplicates prefer **pause/disable** over delete.
6. GTM: the fix lives in a workspace until published. Publishing is a write; before publishing list exactly
   which tags/triggers/variables change. Use Preview (Tag Assistant) to test the draft if possible.
7. `record-change` (applied / partial / failed) with rollback info only if real (GTM: previous container
   version can be republished; many dashboard settings have no undo).
8. After all approved proposals: `verify-begin` → fresh observation → `ingest --kind verify`.

Out-of-scope issues you notice while working: do not touch them. Mention them to the user afterwards.
