#!/usr/bin/env python3
"""Validate knowledge/rules.json and (re)generate knowledge/SOURCES.md.

  python3 scripts/check_knowledge.py            # validate, print stale warnings, regenerate manifest
  python3 scripts/check_knowledge.py --strict   # also fail on stale rules
  python3 scripts/check_knowledge.py --check    # fail if SOURCES.md is out of date (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.knowledge import RULES_PATH, validate_rules_doc  # noqa: E402

MANIFEST = ROOT / "knowledge" / "SOURCES.md"


def render_manifest(doc: dict) -> str:
    lines = [
        "# Documentation-source manifest",
        "",
        "Generated from `knowledge/rules.json` by `scripts/check_knowledge.py` — do not edit by hand.",
        "",
        f"> {doc.get('verification_note', '')}",
        "",
        "| Rule | Platform | Level | Confidence | Checked | Method | Sources |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in doc["rules"]:
        srcs = "<br>".join(r["source_urls"])
        lines.append(
            f"| `{r['id']}` | {r['platform']} | {r['requirement_level']} | {r['confidence']} | {r['date_checked']} | "
            f"{r['verification_method']} | {srcs} |"
        )
    urls = sorted({u for r in doc["rules"] for u in r["source_urls"]})
    lines += ["", "## All official sources", ""] + [f"- {u}" for u in urls] + [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    errors, warnings = validate_rules_doc(doc)
    for e in errors:
        print(f"ERROR {e}")
    for w in warnings:
        print(f"WARN  {w}")
    manifest = render_manifest(doc)
    if a.check:
        if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != manifest:
            print("ERROR knowledge/SOURCES.md is out of date; run scripts/check_knowledge.py")
            return 1
    else:
        MANIFEST.write_text(manifest, encoding="utf-8")
    unconfirmed = [r["id"] for r in doc["rules"] if r["confidence"] != "confirmed"]
    print(f"{len(doc['rules'])} rules, {len(unconfirmed)} unconfirmed, {len(errors)} errors, {len(warnings)} stale")
    if errors or (a.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
