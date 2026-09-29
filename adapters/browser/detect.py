"""Capability detection and adapter selection.

Order of preference:
1. an agent-hosted browser the agent *declared* it has (it can also operate
   dashboards with the user's own logins);
2. in-process Playwright with a launchable Chromium (storefront only);
3. static HTTP (markup only - never enough to verify).
Nothing is assumed: Playwright is probed by actually launching Chromium.
"""

from __future__ import annotations

from typing import Any

from adapters.browser.relay import GenericComputerUseAdapter, RelayAdapter
from adapters.claude.claude_adapter import CLAUDE_TOOLS, ClaudeBrowserAdapter
from adapters.codex.codex_adapter import CODEX_TOOLS, CodexBrowserAdapter


def relay_for(agent_browser: str | None) -> RelayAdapter | None:
    if not agent_browser or agent_browser == "none":
        return None
    host, _, tool = agent_browser.partition(":")
    if host == "claude" and tool in CLAUDE_TOOLS:
        return ClaudeBrowserAdapter(tool)
    if host == "codex" and tool in CODEX_TOOLS:
        return CodexBrowserAdapter(tool)
    if agent_browser == "computer-use":
        return GenericComputerUseAdapter()
    raise ValueError(
        "unknown --agent-browser; use one of: "
        + ", ".join([f"claude:{t}" for t in CLAUDE_TOOLS] + [f"codex:{t}" for t in CODEX_TOOLS] + ["computer-use", "none"])
    )


def probe_playwright() -> dict[str, Any]:
    from adapters.browser.playwright_adapter import PlaywrightAdapter, playwright_available

    if not playwright_available():
        return {"available": False, "reason": "python package 'playwright' not installed"}
    try:
        adapter = PlaywrightAdapter()
    except Exception as exc:  # noqa: BLE001 - report, never pretend
        return {"available": False, "reason": str(exc)[:300]}
    adapter.close()
    return {"available": True}


def detect(agent_browser: str | None = None, probe: bool = True) -> dict[str, Any]:
    relay = relay_for(agent_browser)
    pw = probe_playwright() if probe else {"available": False, "reason": "not probed"}
    if relay:
        recommended = relay.name
    elif pw["available"]:
        recommended = "playwright"
    else:
        recommended = "static-http"
    return {
        "agent_browser": relay.name if relay else None,
        "agent_browser_capabilities": relay.capabilities().to_dict() if relay else None,
        "dashboards_possible": bool(relay and relay.capabilities().dashboards),
        "playwright": pw,
        "static_http": {"available": True, "limits": "markup only; cannot verify behaviour"},
        "recommended": recommended,
        "can_verify_behaviour": bool(relay and relay.capabilities().network_capture) or pw["available"],
    }
