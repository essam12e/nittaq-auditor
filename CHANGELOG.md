# Changelog

## 1.0.0 — 2026-09-29

First release of **مدقق نطاق** (`nittaq-auditor`).

### Added
- `SKILL.md` with the Arabic trigger "مدقق نطاق", AUDIT_ONLY default, OBSERVE → PROPOSE → EXECUTE model,
  authentication hand-off, Merchant Center two-approval stage, and "never" rules.
- Engine (Python ≥ 3.10, stdlib only):
  - explicit workflow state machine (no path from report to execution without approval; no path from
    execution to completion without verification);
  - observation schema, validation and secret redaction;
  - network decoder for GA4, Google Ads, Meta (high confidence) and TikTok/Snapchat (best effort, `UNPARSED`
    when undecodable);
  - validators: GA4, GTM, Google Ads, Meta, TikTok, Snapchat, Merchant Center; cross-platform duplicate engine;
  - 12-state service status model; findings tagged observed / inferred / unverified / manual-check;
  - proposals, scoped approval ledger, Arabic reply parser (ambiguity → clarification), destructive-action
    confirmation;
  - write gate (state, scope, Merchant, destructive, official page host, wrong-account protection) with
    single-use authorisation tokens;
  - change records (previous state, rollback only when real) and fresh-evidence verification;
  - Arabic message catalog, text and RTL HTML reports (Tajawal font), false-success guard.
- Browser layer: `BrowserController` interface, safety policy (no typing API, payment/order clicks refused,
  challenge detection), Playwright adapter, static HTTP fallback, Claude/Codex/computer-use relay adapters,
  capability detection.
- CLI `scripts/nittaq.py`; maintenance scripts `check_knowledge.py`, `validate_project.py`, `run_tests.sh`.
- Tests (184, see TEST_RESULTS.md): unit, scenario matrix, workflow/approval safety, and real-Chromium integration tests against a local
  fake Salla-like store.

### Knowledge
- 34 rules in `knowledge/rules.json` with official source URLs, checked 2026-09-29 via web-search excerpts
  (direct page fetch was blocked by the build sandbox). Unconfirmed rules are enforced only as manual checks.
