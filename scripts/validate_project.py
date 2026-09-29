#!/usr/bin/env python3
"""Final-validation checks (spec §54) that are not unit tests.

Checks project structure, SKILL.md frontmatter, absence of secrets, absence of
placeholder code presented as production, and documentation references.
Exit code 1 on any failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED = [
    "SKILL.md", "README.md", "CHANGELOG.md",
    "adapters/browser/controller.py", "adapters/browser/playwright_adapter.py", "adapters/browser/static_http.py",
    "adapters/browser/relay.py", "adapters/claude/claude_adapter.py", "adapters/codex/codex_adapter.py",
    "core/discovery/observation.py", "core/audit/engine.py", "core/approval/ledger.py", "core/approval/parser.py",
    "core/execution/gate.py", "core/verification/verifier.py", "core/reporting/arabic_report.py", "core/state_machine.py",
    "validators/ga4/validator.py", "validators/gtm/validator.py", "validators/google_ads/validator.py",
    "validators/meta/validator.py", "validators/tiktok/validator.py", "validators/snapchat/validator.py",
    "validators/merchant/validator.py",
    "knowledge/rules.json", "knowledge/SOURCES.md", "knowledge/REVIEW_PROCESS.md",
    "knowledge/salla/storefront.md", "knowledge/salla/analytics-events.md", "knowledge/salla/tracking.md",
    "knowledge/salla/limitations.md", "knowledge/google/ga4.md", "knowledge/google/gtm.md",
    "knowledge/google/google-ads.md", "knowledge/google/merchant-center.md", "knowledge/meta/web-tracking.md",
    "knowledge/tiktok/web-tracking.md", "knowledge/snapchat/web-tracking.md",
    "workflows/audit.md", "workflows/connect.md", "workflows/repair.md", "workflows/verify.md", "workflows/merchant.md",
    "reports/templates/messages.ar.json", "schemas/observation.schema.json", "scripts/nittaq.py",
]

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"ghp_[0-9A-Za-z]{30,}"),
    re.compile(r"(?i)(password|passwd|api_key|secret)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"),
    re.compile(r"EAA[0-9A-Za-z]{30,}"),  # Meta access tokens
]
PLACEHOLDER = re.compile(r"(TODO|FIXME|XXX|NotImplementedError|placeholder implementation)")
SCAN_EXT = {".py", ".md", ".json", ".sh", ".toml", ".txt", ".yml", ".yaml"}


def files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if any(part.startswith(".") for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file() and p.suffix in SCAN_EXT and "__pycache__" not in p.parts:
            out.append(p)
    return out


def main() -> int:
    problems: list[str] = []
    for required in REQUIRED:
        if not (ROOT / required).exists():
            problems.append(f"missing {required}")

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
    if not m:
        problems.append("SKILL.md: missing YAML frontmatter")
    else:
        fm = m.group(1)
        if not re.search(r"^name:\s*nittaq-auditor\s*$", fm, re.M):
            problems.append("SKILL.md: name must be nittaq-auditor")
        if "description:" not in fm or "مدقق نطاق" not in fm:
            problems.append("SKILL.md: description must mention the Arabic trigger")
    for needle in ("AUDIT_ONLY", "EXECUTING", "Merchant", "Never"):
        if needle not in skill:
            problems.append(f"SKILL.md: missing section about {needle}")
    if len(skill.splitlines()) > 400:
        problems.append("SKILL.md: too long; move details into knowledge/")

    for p in files():
        rel = p.relative_to(ROOT)
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            if pat.search(text) and "validate_project.py" not in str(rel):
                problems.append(f"possible secret in {rel}: {pat.pattern[:30]}")
        if p.suffix == ".py" and "tests" not in rel.parts and "validate_project.py" not in str(rel):
            for i, line in enumerate(text.splitlines(), 1):
                if PLACEHOLDER.search(line):
                    problems.append(f"placeholder marker in {rel}:{i}: {line.strip()[:80]}")

    # every knowledge markdown file cites at least one official https source and a date
    for md in (ROOT / "knowledge").rglob("*.md"):
        if md.name in ("SOURCES.md", "REVIEW_PROCESS.md"):
            continue
        t = md.read_text(encoding="utf-8")
        if "https://" not in t or "2026-" not in t:
            problems.append(f"{md.relative_to(ROOT)}: needs official source URL and date checked")

    for pr in problems:
        print("FAIL", pr)
    print(f"{'OK' if not problems else 'FAILED'}: {len(REQUIRED)} required paths, {len(files())} files scanned, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
