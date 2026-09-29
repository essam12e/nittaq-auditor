"""Relay adapters for browsers hosted by the *agent* (not by this process).

Claude Code / Codex / computer-use tools can drive a real browser, but only
the agent can call them. A relay adapter therefore produces:

* ``collection_plan()`` - the exact read-only steps the agent performs with
  its own tool, and what to record;
* ``observation_skeleton()`` - the JSON document the agent fills in and then
  passes to ``nittaq.py ingest``.

The agent must record only what it actually saw. Capabilities are declared
per tool: a screenshot-only computer-use tool cannot capture network
requests, so it sets ``network_capture=false`` and services it examines can
never reach CONNECTED_VERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from adapters.browser.controller import Capabilities
from core.discovery.observation import SCHEMA_VERSION

BASE_PLAN = (
    "Open the store home page. Record the page (url, step='home', status).",
    "Read window.dataLayer (JSON-serialisable entries only) if the tool can evaluate JavaScript.",
    "Open one product page (step='view_item').",
    "Click the add-to-cart control once (step='add_to_cart'). Never click payment / confirm-order controls.",
    "Open /cart (step='view_cart').",
    "Click the checkout control once (step='begin_checkout'). If a login / OTP / CAPTCHA appears, STOP: record flow.blocked.begin_checkout='customer_login' or 'captcha'. Never type codes or passwords.",
    "Record every outgoing request to google-analytics.com, googletagmanager.com, googleadservices.com, googleads.g.doubleclick.net, google.com/pagead, facebook.com/tr, connect.facebook.net, analytics.tiktok.com, tr.snapchat.com, sc-static.net: url, method, post_data, page_url, step, page_load_id.",
    "Set flow.blocked.add_payment_info and flow.blocked.purchase to 'financial_transaction' unless the user explicitly asked for and understood a real test order.",
)

DASHBOARD_PLAN = (
    "Only after the storefront pass, and only read screens: open the official dashboard for the service.",
    "If a login, 2FA or CAPTCHA appears, stop and hand control to the user (nittaq.py pause). Never ask for or type credentials.",
    "If several accounts/properties/containers are listed and the right one is not provable from the audited IDs, stop and ask the user.",
    "Record what is visible under dashboards.<service> using the documented fields (see schemas/observation.schema.json).",
    "Do not click Save, Publish, Submit, Delete, Create or any toggle during the audit.",
)


@dataclass
class RelayAdapter:
    name: str
    tool_hint: str
    caps: Capabilities
    extra_plan: tuple[str, ...] = field(default_factory=tuple)

    def capabilities(self) -> Capabilities:
        return self.caps

    def collection_plan(self, include_dashboards: bool = False) -> list[str]:
        steps = list(BASE_PLAN)
        if not self.caps.network_capture:
            steps.insert(0, "This tool cannot capture network requests: leave 'requests' empty and do not infer hits from screenshots.")
        steps.extend(self.extra_plan)
        if include_dashboards:
            steps.extend(DASHBOARD_PLAN)
        return steps

    def observation_skeleton(self, store_url: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "store_url": store_url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "adapter": self.name,
            "capabilities": self.caps.to_dict(),
            "pages": [],
            "requests": [],
            "captured_events": [],
            "flow": {"attempted": [], "completed": [], "blocked": {}},
            "dashboards": {},
            "store_facts": {},
            "notes": [f"collected by the agent with {self.tool_hint}"],
        }


class GenericComputerUseAdapter(RelayAdapter):
    """Screenshot/pointer-based computer use: no network capture."""

    def __init__(self) -> None:
        super().__init__(
            name="computer-use",
            tool_hint="a generic computer-use tool (screenshots + pointer)",
            caps=Capabilities(javascript=True, network_capture=False, interaction=True, dashboards=True),
            extra_plan=(
                "Prefer accessible labels and visible text over coordinates; after each navigation confirm the URL/title before acting.",
            ),
        )
