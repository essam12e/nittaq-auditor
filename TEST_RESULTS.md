# Test results — 1.0.0 (2026-09-29)

Environment: Linux, Python 3.11.15, Python Playwright 1.63.0, Chromium 141.0.7390.37 (headless), ruff, mypy.
Command: `scripts/run_tests.sh` → exit code 0.

| Check | Result |
|---|---|
| `check_knowledge.py --check` | 34 rules, 11 unconfirmed, 0 errors, 0 stale |
| `validate_project.py` (structure, SKILL.md, secrets, placeholders, doc sources) | OK — 46 required paths, 0 problems |
| `ruff check .` | All checks passed |
| `mypy` (core, validators, adapters, scripts) | no issues in 62 source files |
| `unittest discover` | **184 tests, all passed, 0 skipped** |

| Suite | Tests | Covers |
|---|---|---|
| `tests/scenarios/test_tracking_scenarios.py` | 63 | GA4 / GTM / Google Ads / Meta / TikTok / Snapchat matrices, cross-platform duplicates, page-level failures |
| `tests/scenarios/test_merchant_scenarios.py` | 11 | healthy, disapproved, price/availability mismatch, landing page, identifiers, multiple issues, store-side fix, domain, login, multiple accounts |
| `tests/unit/test_core_units.py` | 30 | invocation parsing, network decoding, Salla detection, state-machine invariants, knowledge validation, redaction |
| `tests/unit/test_workflow.py` | 26 | audit-only, refusal, ambiguity, scoped approval, destructive confirmation, gate, verification (verified / failed / stale / unable), Merchant double approval, pause/resume, fail-safe, no persisted secrets |
| `tests/unit/test_approval.py` | 20 | Arabic reply parsing, ledger scope, wrong account / wrong page, new-connection confirmation, Merchant separation |
| `tests/unit/test_browser_layer.py` | 17 | safety policy, capability detection (unavailable / declared / computer-use), relay plans, static fallback, CLI |
| `tests/unit/test_reporting.py` | 13 | Arabic templates, false-success guard, scoped wording, fact vs inference, HTML report |
| `tests/integration/test_playwright_flow.py` | 4 | **real Chromium** against a local fake Salla-like store: capture → decode → classify; broken-store detection; payment button refusal; navigation failure |

## Not live-tested (and why)

| Item | Reason |
|---|---|
| Real Salla storefronts | no approved target store in the build session; the fake store only mimics Salla's shape |
| Real GA4 / Google Ads / Meta / TikTok / Snapchat endpoints | build sandbox network policy blocks those hosts; all third-party hosts were intercepted in tests |
| Platform dashboards (GTM, GA4, Ads, Events Managers, Merchant Center, Salla dashboard) | no accounts / logins; requires an agent browser with the user's sessions |
| Claude relay adapters (Playwright MCP, Claude in Chrome) and computer use | no such tool attached to the build session |
| Codex | not available in the build environment |
| Write operations on any platform | never exercised against real systems; only the gate/record/verify logic is tested |
| TikTok / Snapchat wire formats | not publicly specified; decoded best-effort and require platform test-events confirmation for VERIFIED |
