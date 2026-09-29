"""Codex browser adapter (relay).

Codex can use a browser when one is exposed to it (for example a Playwright
MCP server configured in ``~/.codex/config.toml``). Without such a tool the
Codex adapter is unavailable and the in-process Playwright adapter or the
static HTTP fallback is used instead. Declared conservatively; not live-tested
(see README "Compatibility").
"""

from __future__ import annotations

from adapters.browser.controller import Capabilities
from adapters.browser.relay import RelayAdapter

CODEX_TOOLS: dict[str, tuple[str, Capabilities, tuple[str, ...]]] = {
    "playwright-mcp": (
        "Playwright MCP configured for Codex",
        Capabilities(javascript=True, network_capture=True, interaction=True, dashboards=True),
        (
            "List network requests after each step and copy tracking requests verbatim (url + body).",
            "Read window.dataLayer with the evaluate tool.",
        ),
    ),
}


class CodexBrowserAdapter(RelayAdapter):
    def __init__(self, tool: str = "playwright-mcp"):
        if tool not in CODEX_TOOLS:
            raise ValueError(f"unknown Codex browser tool: {tool}")
        hint, caps, plan = CODEX_TOOLS[tool]
        super().__init__(name=f"codex:{tool}", tool_hint=hint, caps=caps, extra_plan=plan)
