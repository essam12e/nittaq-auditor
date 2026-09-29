"""Claude browser adapter (relay).

Claude Code can reach a browser through MCP servers such as Playwright MCP
(``mcp__playwright__*`` tools: navigate, click, evaluate, network requests)
or Claude in Chrome (``mcp__claude-in-chrome__*``). Which one exists depends
on the user's setup, so the agent declares it (``--agent-browser``) after
checking its own tool list. Capabilities differ per tool and are declared
conservatively.
"""

from __future__ import annotations

from adapters.browser.controller import Capabilities
from adapters.browser.relay import RelayAdapter

CLAUDE_TOOLS: dict[str, tuple[str, Capabilities, tuple[str, ...]]] = {
    "playwright-mcp": (
        "Playwright MCP (browser_navigate, browser_click, browser_evaluate, browser_network_requests)",
        Capabilities(javascript=True, network_capture=True, interaction=True, dashboards=True),
        (
            "Use browser_network_requests after each step to list requests; copy tracking requests verbatim (url + body).",
            "Use browser_evaluate to read window.dataLayer.",
            "Use browser_snapshot (accessibility tree) to find controls by label; do not use coordinates.",
        ),
    ),
    "claude-in-chrome": (
        "Claude in Chrome (the user's real Chrome profile; existing logins)",
        Capabilities(javascript=True, network_capture=True, interaction=True, dashboards=True),
        (
            "Use the network-request reading tool to list tracking requests after each step; if the tool only exposes URLs (no bodies), set capabilities.network_capture=false for body-dependent checks and note it.",
            "The user's existing sessions may be used for dashboards; never change account settings.",
        ),
    ),
}


class ClaudeBrowserAdapter(RelayAdapter):
    def __init__(self, tool: str = "playwright-mcp"):
        if tool not in CLAUDE_TOOLS:
            raise ValueError(f"unknown Claude browser tool: {tool}")
        hint, caps, plan = CLAUDE_TOOLS[tool]
        super().__init__(name=f"claude:{tool}", tool_hint=hint, caps=caps, extra_plan=plan)
