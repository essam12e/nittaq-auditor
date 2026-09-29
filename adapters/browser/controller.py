"""BrowserController: provider-independent browser interface.

The auditing core never talks to a browser directly; it consumes
observations. Adapters that can drive a browser *in-process* implement
``BrowserController`` (e.g. PlaywrightAdapter); adapters for agent-hosted
browser tools (Claude / Codex / computer-use) are relay adapters that tell
the agent how to collect an observation with its own tool.

Safety is enforced here, below every adapter:
* no method exists to type into fields (passwords/OTP can't be entered);
* clicks on payment / order-confirmation controls are refused;
* security challenges are detected and surfaced, never bypassed.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.discovery.salla import FORBIDDEN_ACTION_LABELS
from core.invocation import normalize_ar


class BrowserUnavailable(RuntimeError):
    """Raised when no usable browser exists. Callers must report it, not fake it."""


class UnsafeAction(PermissionError):
    pass


@dataclass(frozen=True)
class Capabilities:
    javascript: bool  # executes page scripts
    network_capture: bool  # can record outgoing requests incl. bodies
    interaction: bool  # can click / navigate like a user
    dashboards: bool = False  # can operate authenticated platform dashboards (agent-driven only)

    def to_dict(self) -> dict[str, bool]:
        return {
            "javascript": self.javascript,
            "network_capture": self.network_capture,
            "interaction": self.interaction,
        }


@dataclass
class Locator:
    """Semantic locator. Coordinates are deliberately not supported."""

    role: str | None = None  # e.g. "button", "link"
    name: str | None = None  # accessible name / visible text
    css: str | None = None  # stable selector (web component, data attribute)

    def describe(self) -> str:
        return self.name or self.css or self.role or "?"


@dataclass
class PageResult:
    url: str
    status: str  # ok | error | timeout | captcha | auth_required | two_factor
    http_status: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_FORBIDDEN_N = tuple(normalize_ar(x) for x in FORBIDDEN_ACTION_LABELS)


class SafetyPolicy:
    """Decisions that no adapter may override."""

    @staticmethod
    def is_forbidden_label(label: str | None) -> bool:
        if not label:
            return False
        n = normalize_ar(label)
        for f in _FORBIDDEN_N:
            if re.search(rf"(?<![\w]){re.escape(f)}(?![\w])", n):
                return True
        return False

    @classmethod
    def check_click(cls, locator: Locator, element_text: str | None = None) -> None:
        for label in (locator.name, element_text):
            if cls.is_forbidden_label(label):
                raise UnsafeAction(f"refusing to click payment/order control: {label!r}")

    # Full-page security challenges (interstitials). Invisible/background
    # captcha scripts present on normal pages are deliberately NOT matched.
    _CHALLENGE = re.compile(
        r"(challenges\.cloudflare\.com|cf-chl-|<title>\s*just a moment|hcaptcha\.com/captcha|recaptcha/api2/bframe|"
        r"attention required! \| cloudflare)",
        re.IGNORECASE,
    )

    @classmethod
    def classify_blocker(cls, html: str, url: str) -> str | None:
        """Markup-level challenge detection. Adapters with a live DOM must also
        check *visible* OTP/password inputs (hidden login modals are common)."""
        if cls._CHALLENGE.search(html or ""):
            return "captcha"
        if re.search(r"/(login|signin|sign-in|auth)(/|\?|$)", url.lower()):
            return "auth_required"
        return None


class BrowserController(ABC):
    name: str = "abstract"

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def open(self, url: str, step: str) -> PageResult: ...

    @abstractmethod
    def html(self) -> str: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    def links(self) -> list[str]: ...

    @abstractmethod
    def click(self, locator: Locator, step: str) -> bool:
        """Click the first visible element matching the locator. Must call
        SafetyPolicy.check_click with the element's text before clicking."""

    @abstractmethod
    def datalayer(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def network_log(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def wait_idle(self, ms: int = 2500) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> BrowserController:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
