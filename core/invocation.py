"""Recognise the Arabic invocation "مدقق نطاق" and extract intent + store URL."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from core.services import GROUP_WORDS, SERVICES, TRACKING_SERVICE_IDS, ordered

TRIGGER = "مدقق نطاق"
TECHNICAL_TRIGGERS = ("nittaq-auditor", "/nittaq-auditor", "nittaq auditor")

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # incl. tatweel


def normalize_ar(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآٱ]", "ا", text)
    text = text.replace("ى", "ي")
    return re.sub(r"\s+", " ", text).strip().lower()


_TRIGGER_N = normalize_ar(TRIGGER)

_URL_RE = re.compile(
    r"(?P<url>(?:https?://)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d{2,5})?(?:/[^\s<>\"'،]*)?)",
    re.IGNORECASE,
)
_LOCAL_URL_RE = re.compile(r"(?P<url>https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{2,5})?(?:/[^\s<>\"'،]*)?)")

INTENT_WELCOME = "welcome"
INTENT_AUDIT = "audit"
INTENT_REPAIR = "repair"
INTENT_VERIFY = "verify"

_REPAIR_WORDS = ("اصلح", "صلح", "اصلاح", "عالج", "fix", "repair")
_VERIFY_WORDS = ("تاكد", "تحقق", "verify", "check connection")


class InvalidStoreUrl(ValueError):
    pass


@dataclass
class InvocationRequest:
    triggered: bool
    intent: str
    store_url: str | None = None
    focus_services: list[str] = field(default_factory=list)  # empty = all tracking services
    merchant_requested: bool = False
    url_error: str | None = None
    raw: str = ""


def is_private_host(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def normalize_store_url(candidate: str, allow_local: bool = False) -> str:
    candidate = candidate.strip().rstrip(".,;:!?)»”")
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        if "://" in candidate:
            raise InvalidStoreUrl("unsupported_scheme")
        candidate = "https://" + candidate
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidStoreUrl("unsupported_scheme")
    host = (parts.hostname or "").lower()
    if not host:
        raise InvalidStoreUrl("missing_host")
    if parts.username or parts.password:
        # Never accept credentials embedded in URLs.
        raise InvalidStoreUrl("credentials_in_url")
    if is_private_host(host) and not allow_local:
        raise InvalidStoreUrl("private_host")
    netloc = host + (f":{parts.port}" if parts.port else "")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _mentions(text_n: str, alias: str) -> bool:
    alias_n = normalize_ar(alias)
    if re.fullmatch(r"[a-z0-9 ]+", alias_n):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias_n)}(?![a-z0-9])", text_n) is not None
    return alias_n in text_n


def detect_services(text: str, expand_groups: bool = True) -> tuple[list[str], bool]:
    """Return (tracking service ids mentioned, merchant mentioned).

    ``expand_groups`` maps group words ("جوجل", "البيكسلات") to their services;
    approval parsing disables it because a group word is too broad to approve."""
    text_n = normalize_ar(text)
    found: set[str] = set()
    merchant = False
    for s in SERVICES:
        if any(_mentions(text_n, a) for a in s.aliases):
            if s.sensitive:
                merchant = True
            else:
                found.add(s.id)
    if not found and expand_groups:
        if any(_mentions(text_n, w) for w in GROUP_WORDS["google"]) and not merchant:
            found.update(("ga4", "gtm", "google_ads"))
        if any(_mentions(text_n, w) for w in GROUP_WORDS["pixels"]):
            found.update(("meta", "tiktok", "snapchat"))
    return ordered(found), merchant


def parse_invocation(text: str, allow_local: bool = False) -> InvocationRequest:
    raw = text
    text_n = normalize_ar(text)
    triggered = _TRIGGER_N in text_n or any(t in text_n for t in TECHNICAL_TRIGGERS)
    if not triggered:
        return InvocationRequest(triggered=False, intent=INTENT_WELCOME, raw=raw)

    rest = text_n.replace(_TRIGGER_N, " ", 1)
    for t in TECHNICAL_TRIGGERS:
        rest = rest.replace(t, " ")

    store_url = None
    url_error = None
    match = (_LOCAL_URL_RE.search(text) if allow_local else None) or _URL_RE.search(text)
    if match:
        try:
            store_url = normalize_store_url(match.group("url"), allow_local=allow_local)
        except InvalidStoreUrl as exc:
            url_error = str(exc)
        rest = rest.replace(normalize_ar(match.group("url")), " ")

    focus, merchant = detect_services(rest)
    if any(w in rest for w in _REPAIR_WORDS):
        intent = INTENT_REPAIR
    elif any(w in rest for w in _VERIFY_WORDS):
        intent = INTENT_VERIFY
    elif store_url or focus or merchant or rest.strip():
        intent = INTENT_AUDIT
    else:
        intent = INTENT_WELCOME
    if focus == list(TRACKING_SERVICE_IDS):
        focus = []
    return InvocationRequest(
        triggered=True,
        intent=intent,
        store_url=store_url,
        focus_services=focus,
        merchant_requested=merchant,
        url_error=url_error,
        raw=raw,
    )
