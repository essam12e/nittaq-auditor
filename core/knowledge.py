"""Platform knowledge registry (knowledge/rules.json).

Validators cite rules by id. A rule with ``confidence == "unconfirmed"`` may
only produce MANUAL_CHECK / INFERRED findings, never a confirmed violation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "knowledge" / "rules.json"

REQUIRED_FIELDS = (
    "id",
    "platform",
    "title",
    "statement",
    "requirement_level",
    "source_urls",
    "date_checked",
    "verification_method",
    "confidence",
    "validators",
)
REQUIREMENT_LEVELS = {"required", "conditional", "recommended", "observation"}
CONFIDENCE = {"confirmed", "unconfirmed"}
VERIFICATION_METHODS = {
    "official_page_read",
    "web_search_excerpt",
    "derived_from_official_requirement",
    "engineering_inference",
    "manual_review",
}
OFFICIAL_DOMAINS = (
    "developers.google.com",
    "support.google.com",
    "developers.facebook.com",
    "www.facebook.com",
    "ads.tiktok.com",
    "business-api.tiktok.com",
    "businesshelp.snapchat.com",
    "developers.snap.com",
    "docs.salla.dev",
    "help.salla.sa",
    "apps.salla.sa",
)


class UnknownRule(KeyError):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    platform: str
    title: str
    statement: str
    requirement_level: str
    source_urls: tuple[str, ...]
    date_checked: str
    verification_method: str
    confidence: str
    validators: tuple[str, ...]
    notes: str = ""

    @property
    def confirmed(self) -> bool:
        return self.confidence == "confirmed" and self.verification_method != "engineering_inference"


def validate_rules_doc(doc: dict[str, Any], today: date | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Stale rules are warnings, schema problems errors."""
    errors: list[str] = []
    warnings: list[str] = []
    today = today or date.today()
    interval = int(doc.get("review_interval_days", 90))
    seen: set[str] = set()
    for i, r in enumerate(doc.get("rules", [])):
        rid = r.get("id", f"#{i}")
        for f in REQUIRED_FIELDS:
            if f not in r or r[f] in (None, "", []):
                errors.append(f"{rid}: missing {f}")
        if rid in seen:
            errors.append(f"{rid}: duplicate id")
        seen.add(rid)
        if r.get("requirement_level") not in REQUIREMENT_LEVELS:
            errors.append(f"{rid}: bad requirement_level")
        if r.get("confidence") not in CONFIDENCE:
            errors.append(f"{rid}: bad confidence")
        if r.get("verification_method") not in VERIFICATION_METHODS:
            errors.append(f"{rid}: bad verification_method")
        for u in r.get("source_urls", []):
            if not str(u).startswith("https://"):
                errors.append(f"{rid}: non-https source {u}")
            elif not any(f"//{d}/" in u or u.endswith(f"//{d}") for d in OFFICIAL_DOMAINS):
                errors.append(f"{rid}: source is not an official domain: {u}")
        try:
            checked = date.fromisoformat(str(r.get("date_checked")))
            if (today - checked).days > interval:
                warnings.append(f"{rid}: last checked {checked} (> {interval} days) - review required")
        except ValueError:
            errors.append(f"{rid}: bad date_checked")
    return errors, warnings


@lru_cache(maxsize=1)
def load_rules(path: str = str(RULES_PATH)) -> dict[str, Rule]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errors, _ = validate_rules_doc(doc)
    if errors:
        raise ValueError("invalid knowledge/rules.json: " + "; ".join(errors))
    rules = {}
    for r in doc["rules"]:
        rules[r["id"]] = Rule(
            id=r["id"],
            platform=r["platform"],
            title=r["title"],
            statement=r["statement"],
            requirement_level=r["requirement_level"],
            source_urls=tuple(r["source_urls"]),
            date_checked=r["date_checked"],
            verification_method=r["verification_method"],
            confidence=r["confidence"],
            validators=tuple(r["validators"]),
            notes=r.get("notes", ""),
        )
    return rules


def rule(rule_id: str) -> Rule:
    rules = load_rules()
    if rule_id not in rules:
        raise UnknownRule(rule_id)
    return rules[rule_id]
