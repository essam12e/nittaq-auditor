# Codex adapter

Codex supports `SKILL.md`-based skills and MCP servers. With a Playwright MCP server configured for Codex,
use `--agent-browser codex:playwright-mcp`; the flow is identical to Claude's relay adapter (`plan` →
perform read-only steps → `ingest`). Without a browser tool Codex can still run the in-process Playwright
adapter (`collect`) if Python Playwright + Chromium are installed, or the static fallback.

Status: **designed to support, not tested with Codex** in this build.
