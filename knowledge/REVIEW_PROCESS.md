# Knowledge review process

Platform requirements change. They live in data (`knowledge/rules.json`) and short notes
(`knowledge/**/*.md`), separate from the core workflow (`core/`) and validators (`validators/`).

## When
- Every `review_interval_days` (90) — `python3 scripts/check_knowledge.py` warns about stale rules and exits 1
  with `--strict`.
- Whenever a platform announces changes to events/parameters (GA4, Google Ads, Meta, TikTok, Snapchat,
  Merchant Center, Salla).

## How (per rule)
1. Open every URL in `source_urls` (official domains only — the checker rejects others).
2. Compare with `statement`. If unchanged: update `date_checked`, set
   `verification_method` to `official_page_read`, and `confidence` to `confirmed` if it was `unconfirmed`
   and the page states it explicitly.
3. If changed: update the rule and the matching Markdown note, adjust the validator, and add/adjust a scenario
   test in `tests/scenarios/`.
4. If the documentation is ambiguous: keep or set `confidence: unconfirmed`. Validators downgrade findings from
   unconfirmed rules to "manual check" — never invent an answer.
5. Run `python3 scripts/check_knowledge.py && python3 scripts/validate_project.py`, then the test suite.
6. Record the change in `CHANGELOG.md` (section "Knowledge").

## Build-time status (2026-09-29)
The build sandbox's network policy blocked direct page fetches of all official documentation domains. Rules
were confirmed from **web-search excerpts of the official pages** (`verification_method: web_search_excerpt`).
Rules that could not be confirmed that way are `unconfirmed`. The first maintainer review with full page access
should upgrade `verification_method` to `official_page_read` rule by rule.
