# مدقق نطاق — nittaq-auditor

A safety-first AI skill that **audits, diagnoses, and (only with explicit approval) connects, repairs and
verifies** analytics and advertising tracking on **Salla (سلة)** stores. The whole end-user experience is
Arabic. It runs in agent environments that support `SKILL.md` skills: Claude Code is the primary target, and
Codex is designed to be supported.

Services: Google Analytics 4 · Google Tag Manager · Google Ads conversions · Meta Pixel · TikTok Pixel ·
Snapchat Pixel · Google Merchant Center (a separate, last stage with two approvals).

---

## What it does

```
STORE → DISCOVERY → AUDIT → DIAGNOSIS → ARABIC REPORT → USER APPROVAL → EXECUTION → VERIFICATION → RE-AUDIT → (MERCHANT) → FINAL REPORT
```

- **Read-only by default (AUDIT_ONLY).** It inspects the storefront (and dashboards, when a browser with the
  user's own logins is available), decodes the real tracking requests, and classifies every service into one of
  12 explicit states. Examples: `NOT_CONNECTED`, `DETECTED`, `CONNECTED_VERIFIED`, `DUPLICATE_EVENTS`,
  `UNABLE_TO_VERIFY`.
- **An ID is never proof.** A `G-…`, `GTM-…`, pixel ID, or conversion action existing gets you `DETECTED` at
  most. `CONNECTED_VERIFIED` requires decoded runtime hits for the funnel steps actually exercised, with no
  issues.
- **Every finding has evidence** and is labelled *observed fact*, *inference*, *unverified*, or *needs manual
  check*.
- **Proposals, not actions.** Problems and missing integrations become numbered proposals (`P1…`). Nothing
  changes until the user approves those exact proposals. Destructive ones also need `أؤكد P#`.
- **Write gate.** Before any save or publish, the engine checks all of these:
  - the workflow state;
  - the approval scope;
  - the separate Merchant approval (for Merchant changes);
  - the destructive-action confirmation;
  - the official platform host;
  - the account/property/container ID (wrong-account protection).

  Each authorization is a single-use token.
- **Verification after every change**, using a *fresh* observation. "Saved" never becomes "verified".
- **Merchant Center** runs last and needs two approvals: one to inspect, and a separate one to modify. Reports
  say where each fix really belongs (often Salla product data, not Merchant settings).

## Installation

Requirements: Python ≥ 3.10. The runtime uses only the standard library. Optional: Python Playwright plus a
Chromium build for in-process browser audits.

### Claude Code
```bash
# personal skill
git clone <this repo> ~/.claude/skills/nittaq-auditor
# or project skill
git clone <this repo> .claude/skills/nittaq-auditor
# optional in-process browser
pip install playwright && python -m playwright install chromium   # or set NITTAQ_CHROMIUM_PATH
```
Claude loads `SKILL.md` automatically. Invoke it by writing **مدقق نطاق**.

For dashboard work (GTM, Google Ads, Events Managers, Merchant Center), give Claude a browser tool such as the
Playwright MCP server or Claude in Chrome. You log in yourself; the skill never handles credentials.

### Codex (designed to support — not tested)
Copy or clone the folder into the Codex skills directory (for example `~/.codex/skills/nittaq-auditor`).
Optionally configure a Playwright MCP server for Codex, and use `--agent-browser codex:playwright-mcp`.

## Usage

```
مدقق نطاق
مدقق نطاق https://example.com
مدقق نطاق افحص جوجل | افحص البيكسلات | افحص Meta | افحص TikTok | افحص Snapchat | افحص Merchant
مدقق نطاق اصلح مشاكل التتبع
مدقق نطاق تأكد من الربط
```

Normally the user only sends the trigger, then the store URL, then approves or rejects clearly described
actions. The agent drives the engine through `scripts/nittaq.py` (see `SKILL.md`). Each command prints JSON
with an Arabic `text` field that the agent shows verbatim:

| Command | Purpose |
|---|---|
| `welcome`, `start --text` | invocation, session creation |
| `detect --agent-browser X` | honest capability detection (Chromium is actually launched) |
| `plan` / `ingest` | agent-browser collection plan → validated observation |
| `collect [--adapter static]` | in-process Playwright flow, or markup-only fallback |
| `reply --text` | approvals, refusals, destructive confirmation, Merchant questions |
| `pause` / `resume` / `fail` | login, 2FA, CAPTCHA, multiple accounts, unexpected UI, safe stop |
| `authorize` / `record-change` | gated writes with a change record |
| `verify-begin`, `ingest --kind verify` | post-change verification and re-audit |
| `report --format text\|json\|html` | Arabic report (HTML is RTL and uses the bundled Tajawal font) |

## Browser requirements

| Environment | What is possible |
|---|---|
| Agent browser with network capture (for example Playwright MCP) | full storefront audit plus read-only dashboards plus approved changes |
| In-process Playwright + Chromium (`collect`) | full storefront audit (no dashboards, no changes) |
| Screenshot-only computer use | observations, but no network capture, so never `CONNECTED_VERIFIED` |
| Nothing (`--adapter static`) | markup only, so at most `DETECTED`; the user is told this plainly |

The storefront flow goes home → one product → add to cart once → cart → click checkout once. It stops at any
login, OTP or CAPTCHA wall. It **refuses to click** payment or confirm-order controls, and has no API for
typing into fields.

## Security model

- It never asks for, accepts, types, stores or logs passwords, OTPs, 2FA codes or cookies. You finish logins
  yourself, and the session resumes at the same point.
- Observations are redacted before they are saved: secret-looking keys, cookies, auth headers, bearer tokens
  and JWTs are removed. Session files are `0600` and stored under `$NITTAQ_HOME` (default `./.nittaq`).
- The static fetcher refuses private and loopback addresses (SSRF guard). It also refuses store URLs that
  contain credentials.
- It does not bypass CAPTCHA, MFA or platform security. It never changes account security settings.
- It never places orders or payments to test tracking.

## Approval model

| Level | Allowed |
|---|---|
| OBSERVE | open pages, inspect storefront, network, tags and dashboards, detect duplicates, report |
| PROPOSE | explain problem, impact, fix, and exactly what would change; ask |
| EXECUTE | only approved proposals, only in state `EXECUTING`, only after `authorize`; then verify |

Approval scope is tracked in an in-task ledger:
- "موافق على GA4" does not approve Meta.
- A tracking approval never approves Merchant.
- Merchant inspection approval never approves Merchant modification.
- Unclear replies such as "ربما" or "جوجل تمام" lead to a clarification question, never execution.

## Testing

```bash
scripts/run_tests.sh                       # knowledge + structure checks, ruff/mypy if installed, all tests
NITTAQ_SKIP_BROWSER=1 scripts/run_tests.sh # skip real-browser tests
```

What is covered:
- the full scenario matrix for GA4, GTM, Google Ads, Meta, TikTok, Snapchat and Merchant;
- cross-platform duplicate detection;
- approval scoping and ambiguity handling;
- the write gate (wrong account, wrong page, destructive, Merchant);
- state-machine invariants, including stale verification evidence and failed or unable-to-verify outcomes;
- the false-success guard and Arabic template validation;
- redaction and file permissions;
- browser-unavailable behaviour;
- the static fallback and the CLI.

**Real-browser integration tests** run Chromium via Playwright against a *local fake Salla-like store*
(`tests/fixtures/fake_store.py`), with every third-party host intercepted. They prove the adapter, flow, decoder
and validators work together, and that payment buttons are never clicked. **They do not prove anything about
real Salla stores or real platform endpoints.**

## Tested vs designed to support

| Area | Status |
|---|---|
| Engine, validators, approval, gate, verification, reports (unit + scenario tests) | **Tested** |
| In-process Playwright adapter + storefront flow (local fake store, real Chromium) | **Tested** |
| Static HTTP fallback (local server) | **Tested** |
| CLI end-to-end (subprocess) | **Tested** |
| Live Salla stores | **Not live-tested.** The build sandbox had no approved target store |
| Real GA4 / Ads / Meta / TikTok / Snap endpoints and dashboards | **Not live-tested.** Sandbox network policy, no accounts |
| Claude relay adapters (Playwright MCP, Claude in Chrome), computer use | **Designed to support.** No such tool was attached during the build |
| Codex | **Designed to support.** Not tested |
| TikTok / Snapchat payload decoding | **Best effort.** Formats are not publicly specified; `UNPARSED` otherwise, and verification needs the platform's test-events view |

## Updating platform knowledge

Requirements live in `knowledge/rules.json` (source URLs, check date, requirement level, confidence,
validators) and in short notes under `knowledge/`. The manifest is `knowledge/SOURCES.md`, generated by
`scripts/check_knowledge.py`. The review process is in `knowledge/REVIEW_PROCESS.md`.

Rules marked `unconfirmed` only produce "needs manual check" findings. At build time (2026-09-29), direct
fetches of the official documentation sites were blocked by the sandbox. Rules were therefore checked against
web-search excerpts of the official pages, and each rule records that.

## Troubleshooting

| Symptom | Cause / action |
|---|---|
| Everything is `DETECTED` / `UNABLE_TO_VERIFY` | Static fallback was used. Install Playwright + Chromium, or give the agent a browser tool |
| `begin_checkout` untested (`customer_login`) | The store requires shopper OTP login. Log in yourself, then re-run, or accept it as untested |
| Purchase untested | Expected: no real orders are placed |
| TikTok/Snap `PARTIALLY_VERIFIED` | Confirm in the platform's Test Events view (recorded as `test_events_confirmed`) |
| `write_refused` (exit 3) | A gate blocked the write: not approved, wrong page, wrong account, or destructive not confirmed |
| `بيانات التحقق قديمة` | The verification observation was collected before the change. Collect again |
| Chromium won't launch | Set `NITTAQ_CHROMIUM_PATH` to a Chromium binary |

## Limitations

- Server-side events (Meta CAPI, TikTok Events API, Snap CAPI, Salla Cloud Mode) are invisible to a browser.
  Deduplication is checked only for the browser half.
- Purchase-only behaviour (conversion value, `transaction_id` uniqueness) needs real orders, which the skill
  won't create.
- Salla dashboard menu labels and some integration details are not publicly documented. They must be
  confirmed live before any change, and the skill stops when the UI is unexpected.
- Merchant Center re-reviews take time. Post-fix verification may legitimately end as `unable_to_verify`.
- No claim of 100% reliability. The design goal is to fail safely, require evidence, and ask before changing
  anything.

## Project layout

```
SKILL.md  README.md  CHANGELOG.md  pyproject.toml
adapters/   browser/ (controller, playwright, static, relay, flow, detect) · claude/ · codex/
core/       discovery/ audit/ approval/ execution/ verification/ reporting/ · state_machine · workflow · session
validators/ ga4/ gtm/ google_ads/ meta/ tiktok/ snapchat/ merchant/
knowledge/  rules.json · SOURCES.md · REVIEW_PROCESS.md · salla/ google/ meta/ tiktok/ snapchat/
workflows/  audit · connect · repair · verify · merchant
reports/templates/messages.ar.json     schemas/observation.schema.json
scripts/    nittaq.py · check_knowledge.py · validate_project.py · run_tests.sh
tests/      unit/ scenarios/ integration/ fixtures/
assets/fonts/Tajawal-Medium.ttf
```

`validators/google_ads` uses an underscore instead of the spec's `google-ads`, because Python packages can't
contain hyphens.
