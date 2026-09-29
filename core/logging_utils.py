"""Developer logging with secret redaction.

Developer logs are English/technical and separate from Arabic user reports.
Passwords, OTP codes, tokens, cookies and auth headers must never be logged
or persisted; ``redact`` is applied to every log record and to every
observation before it is stored in a session file.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

REDACTED = "[REDACTED]"

# Keys whose values are always secret, wherever they appear.
SECRET_KEYS = re.compile(
    r"(pass(word|wd)?|pwd|otp|one[_-]?time|2fa|mfa|totp|verification[_-]?code|"
    r"secret|token|access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|"
    r"authorization|auth|cookie|set-cookie|session(id)?|sid|csrf|xsrf|bearer|credential)",
    re.IGNORECASE,
)

# key=value pairs inside URLs / bodies / free text.
_KV_PATTERN = re.compile(
    r"(?P<key>(?:pass(?:word|wd)?|pwd|otp|code_verifier|access_token|refresh_token|id_token|"
    r"token|api[_-]?key|secret|session(?:id)?|sid|auth|authorization|cookie))"
    r"(?P<sep>\s*[=:]\s*)(?P<val>\"[^\"]*\"|'[^']*'|[^&\s;,\"']+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")

# Keys in structured data that are safe even though they match SECRET_KEYS loosely.
_SAFE_KEYS = {"event_id", "eventid", "transaction_id", "auth_state", "tracking_id"}


def redact_text(text: str) -> str:
    if not text:
        return text
    text = _BEARER.sub(r"\1" + REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    return _KV_PATTERN.sub(lambda m: f"{m.group('key')}{m.group('sep')}{REDACTED}", text)


def redact(value: Any, _key: str | None = None) -> Any:
    """Recursively redact secrets from JSON-like data."""
    if _key is not None and _key.lower() not in _SAFE_KEYS and SECRET_KEYS.fullmatch(_key.strip()):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(a) if isinstance(a, (str, dict, list)) else a for a in record.args)
        return True


def get_logger(name: str = "nittaq") -> logging.Logger:
    logger = logging.getLogger(name)
    if not getattr(logger, "_nittaq_configured", False):
        level = os.environ.get("NITTAQ_LOG_LEVEL", "WARNING").upper()
        logger.setLevel(getattr(logging, level, logging.WARNING))
        handler = logging.StreamHandler()  # stderr: never mixed with user-facing stdout
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
        logger.propagate = False
        logger._nittaq_configured = True  # type: ignore[attr-defined]
    return logger
