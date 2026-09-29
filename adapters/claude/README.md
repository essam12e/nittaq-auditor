# Claude adapter

Claude Code reaches browsers through tools the user has configured, for example:

| `--agent-browser` | Tool | Network bodies | Dashboards with user's logins |
|---|---|---|---|
| `claude:playwright-mcp` | Playwright MCP server (`mcp__playwright__browser_*`) | yes (`browser_network_requests`) | yes (user logs in inside the opened browser) |
| `claude:claude-in-chrome` | Claude in Chrome extension | depends on tool version — set `network_capture=false` if bodies are not available | yes (existing Chrome profile) |
| `computer-use` | generic screenshot/pointer computer use | no | yes |

The Python side cannot call these tools; `nittaq.py plan --agent-browser <id>` gives Claude the read-only
collection steps and an observation skeleton, and `ingest` validates what Claude recorded.

Status: **designed to support, not live-tested** in this build (no such tool was attached to the build
session). The in-process Playwright adapter was tested instead (see README → Testing).
