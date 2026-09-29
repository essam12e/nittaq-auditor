"""Observation schema: the normalised record of what was actually observed.

An observation is produced by a browser adapter (Playwright, static HTTP) or
recorded by the agent from its own browser tool (Claude / Codex adapters).
It is validated, redacted and then turned into an ``AuditContext`` that the
validators consume. Validators never see anything that is not in an
observation, which is what makes "no evidence -> no verification" enforceable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from core.discovery.html_scanner import HtmlScan, scan_html
from core.discovery.network_parser import LoaderDetection, parse_request
from core.discovery.salla import classify_page, is_salla_store
from core.logging_utils import redact
from core.models import EvidenceSource, PlatformEvent

SCHEMA_VERSION = 1
PAGE_STATUSES = {"ok", "error", "auth_required", "captcha", "two_factor", "blocked", "timeout", "user_action_required"}
MAX_HTML_CHARS = 2_000_000
MAX_BODY_CHARS = 64_000


class ObservationError(ValueError):
    pass


def validate_observation(obs: dict[str, Any]) -> list[str]:
    """Return a list of schema problems (empty = valid)."""
    errs: list[str] = []
    if not isinstance(obs, dict):
        return ["observation must be an object"]
    if obs.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(obs.get("store_url"), str) or not obs["store_url"]:
        errs.append("store_url is required")
    if not isinstance(obs.get("adapter"), str):
        errs.append("adapter is required")
    caps = obs.get("capabilities")
    if not isinstance(caps, dict):
        errs.append("capabilities object is required")
    else:
        for k in ("javascript", "network_capture", "interaction"):
            if not isinstance(caps.get(k), bool):
                errs.append(f"capabilities.{k} must be boolean")
    for key in ("pages", "requests", "captured_events"):
        if key in obs and not isinstance(obs[key], list):
            errs.append(f"{key} must be a list")
    for i, p in enumerate(obs.get("pages") or []):
        if not isinstance(p, dict) or not isinstance(p.get("url"), str):
            errs.append(f"pages[{i}].url is required")
            continue
        st = p.get("status", "ok")
        if st not in PAGE_STATUSES:
            errs.append(f"pages[{i}].status invalid: {st}")
    for i, r in enumerate(obs.get("requests") or []):
        if not isinstance(r, dict) or not isinstance(r.get("url"), str):
            errs.append(f"requests[{i}].url is required")
    for i, e in enumerate(obs.get("captured_events") or []):
        if not isinstance(e, dict) or not e.get("platform") or not e.get("name"):
            errs.append(f"captured_events[{i}] requires platform and name")
        elif not e.get("evidence_note"):
            errs.append(f"captured_events[{i}].evidence_note is required (what was seen, where)")
    return errs


def sanitize_observation(obs: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets, drop cookies/headers that may carry credentials, cap sizes."""
    clean = redact(obs)
    for p in clean.get("pages") or []:
        if isinstance(p.get("html"), str) and len(p["html"]) > MAX_HTML_CHARS:
            p["html"] = p["html"][:MAX_HTML_CHARS]
        hdrs = p.get("headers")
        if isinstance(hdrs, dict):
            p["headers"] = {k: v for k, v in hdrs.items() if k.lower() not in ("set-cookie", "cookie", "authorization")}
    for r in clean.get("requests") or []:
        r.pop("headers", None)
        r.pop("cookies", None)
        if isinstance(r.get("post_data"), str) and len(r["post_data"]) > MAX_BODY_CHARS:
            r["post_data"] = r["post_data"][:MAX_BODY_CHARS]
    clean.pop("cookies", None)
    clean.pop("storage_state", None)
    return clean


@dataclass
class AuditContext:
    store_url: str
    adapter: str
    javascript: bool
    network_capture: bool
    interaction: bool
    events: list[PlatformEvent] = field(default_factory=list)
    loaders: list[LoaderDetection] = field(default_factory=list)
    html_ids: dict[str, set[str]] = field(default_factory=dict)
    json_ld_products: list[dict[str, Any]] = field(default_factory=list)
    datalayer: list[dict[str, Any]] = field(default_factory=list)  # entries tagged with page/step
    pages: list[dict[str, Any]] = field(default_factory=list)
    steps_attempted: list[str] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)
    steps_blocked: dict[str, str] = field(default_factory=dict)
    dashboards: dict[str, dict[str, Any]] = field(default_factory=dict)
    store_currency: str | None = None
    store_currency_source: str | None = None
    is_salla: bool = False
    salla_reasons: list[str] = field(default_factory=list)
    page_errors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def behavioral(self) -> bool:
        """True when real runtime behaviour (JS + network) was observed."""
        return self.javascript and self.network_capture

    def events_for(self, platform: str) -> list[PlatformEvent]:
        return [e for e in self.events if e.platform == platform]

    def loaders_for(self, platform: str) -> list[LoaderDetection]:
        return [ld for ld in self.loaders if ld.platform == platform]

    def ids_for(self, platform: str) -> set[str]:
        ids = {e.tracking_id for e in self.events_for(platform) if e.tracking_id}
        ids |= {ld.tracking_id for ld in self.loaders_for(platform) if ld.tracking_id}
        ids |= self.html_ids.get(platform, set())
        return {i for i in ids if i}

    def datalayer_events(self) -> list[dict[str, Any]]:
        return [d for d in self.datalayer if isinstance(d.get("entry"), dict) and d["entry"].get("event")]


def build_context(obs: dict[str, Any]) -> AuditContext:
    errs = validate_observation(obs)
    if errs:
        raise ObservationError("; ".join(errs))
    obs = sanitize_observation(obs)
    caps = obs["capabilities"]
    ctx = AuditContext(
        store_url=obs["store_url"],
        adapter=obs["adapter"],
        javascript=caps["javascript"],
        network_capture=caps["network_capture"],
        interaction=caps["interaction"],
    )
    salla_signals: list[str] = []
    headers_all: dict[str, str] = {}
    for idx, page in enumerate(obs.get("pages") or []):
        step = page.get("step") or classify_page(page["url"]) or "other"
        page = {**page, "step": step, "page_load_id": page.get("page_load_id", idx)}
        ctx.pages.append({k: v for k, v in page.items() if k != "html"})
        status = page.get("status", "ok")
        if status != "ok":
            ctx.page_errors.append({"url": page["url"], "step": step, "status": status, "error": page.get("error")})
        html = page.get("html")
        if isinstance(html, str) and html:
            scan: HtmlScan = scan_html(html)
            for platform, ids in scan.ids.items():
                ctx.html_ids.setdefault(platform, set()).update(ids)
            for platform, tid in scan.loaders:
                ctx.loaders.append(
                    LoaderDetection(platform, tid, "(markup)", page["url"], step, page["page_load_id"], EvidenceSource.HTML)
                )
            for prod in scan.json_ld_products:
                ctx.json_ld_products.append({**prod, "page_url": page["url"]})
            salla_signals.extend(scan.salla_signals)
        if isinstance(page.get("headers"), dict):
            headers_all.update({str(k): str(v) for k, v in page["headers"].items()})
        for entry in page.get("datalayer") or []:
            if isinstance(entry, dict):
                ctx.datalayer.append({"entry": entry, "page_url": page["url"], "step": step, "page_load_id": page["page_load_id"]})

    for seq, req in enumerate(obs.get("requests") or []):
        if not req.get("step") and req.get("page_url"):
            req = {**req, "step": classify_page(str(req["page_url"])) or "other"}
        evs, lds = parse_request(req, seq)
        ctx.events.extend(evs)
        ctx.loaders.extend(lds)

    base = len(obs.get("requests") or [])
    for i, ce in enumerate(obs.get("captured_events") or []):
        ctx.events.append(
            PlatformEvent(
                platform=str(ce["platform"]),
                name=str(ce["name"]),
                tracking_id=ce.get("tracking_id"),
                params=dict(ce.get("params") or {}),
                source=EvidenceSource.AGENT_REPORT,
                page_url=ce.get("page_url"),
                step=ce.get("step"),
                page_load_id=ce.get("page_load_id"),
                seq=base + i,
                parse_confidence="agent_reported",
            )
        )

    flow = obs.get("flow") or {}
    ctx.steps_attempted = list(flow.get("attempted") or [])
    ctx.steps_completed = list(flow.get("completed") or [])
    ctx.steps_blocked = dict(flow.get("blocked") or {})
    if not ctx.steps_completed:
        ctx.steps_completed = [p["step"] for p in ctx.pages if p.get("status", "ok") == "ok"]
    ctx.dashboards = {k: v for k, v in (obs.get("dashboards") or {}).items() if isinstance(v, dict)}

    facts = obs.get("store_facts") or {}
    if facts.get("currency"):
        ctx.store_currency = str(facts["currency"]).upper()
        ctx.store_currency_source = str(facts.get("currency_source") or "store_facts")
    else:
        currencies = Counter(
            str(o.get("priceCurrency")).upper()
            for p in ctx.json_ld_products
            for o in p.get("offers", [])
            if o.get("priceCurrency")
        )
        if currencies:
            ctx.store_currency, _ = currencies.most_common(1)[0]
            ctx.store_currency_source = "json_ld_offers"
    ctx.is_salla, ctx.salla_reasons = is_salla_store(salla_signals, headers_all)
    if facts.get("platform") == "salla" and not ctx.is_salla:
        ctx.salla_reasons.append("declared_by_agent")
        ctx.is_salla = True
    ctx.notes = [str(n) for n in obs.get("notes") or []]
    return ctx
