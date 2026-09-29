"""False-success guard.

Every user-facing text passes through ``check_text`` before it is shown.
Unqualified success claims are rejected: success must be phrased as
"verified within the tests performed", and "no problems" must be scoped to
the checks that could actually run.
"""

from __future__ import annotations

import re

from core.invocation import normalize_ar

# Phrases that claim success/absence of problems without evidence scoping.
FORBIDDEN = (
    "تم الربط بنجاح",
    "تم الاصلاح بنجاح",
    "لا توجد مشاكل",
    "لا يوجد اي مشاكل",
    "لا توجد اي مشكله",
    "لا توجد اي مشكلة",
    "لا توجد أي مشكلة",
    "كل شيء يعمل",
    "كل شي يعمل",
    "يعمل بشكل مثالي",
    "مضمون",
    "100%",
    "١٠٠٪",
)
# "تم الإصلاح." as a standalone claim (not followed by verification wording).
_BARE_FIXED = re.compile(r"تم الاصلاح\s*[.!]?\s*($|\n)")


class FalseSuccessError(ValueError):
    pass


def violations(text: str) -> list[str]:
    n = normalize_ar(text.replace("\n", " \n "))
    found = [p for p in FORBIDDEN if normalize_ar(p) in n]
    if _BARE_FIXED.search(normalize_ar(text)):
        found.append("تم الإصلاح")
    return found


def check_text(text: str) -> str:
    v = violations(text)
    if v:
        raise FalseSuccessError(f"unqualified success claim(s): {v}")
    return text
