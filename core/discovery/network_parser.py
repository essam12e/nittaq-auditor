"""Decode captured network requests into platform events and loader detections.

Only *observed* requests are decoded; nothing is synthesised. When a request
clearly belongs to a platform but cannot be decoded reliably, an event with
name ``UNPARSED`` and ``parse_confidence="best_effort"`` is produced so the
validators can report the limitation instead of guessing.

Endpoint patterns are recorded in ``knowledge/rules.json`` (``net.*`` rules).
Hosts/paths for TikTok and Snapchat collection endpoints are *not* publicly
specified by the vendors and are therefore decoded best-effort.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from core.models import EvidenceSource, PlatformEvent


@dataclass
class LoaderDetection:
    platform: str  # ga4 | gtm | google_ads | google_tag | meta | tiktok | snapchat
    tracking_id: str | None
    url: str
    page_url: str | None = None
    step: str | None = None
    page_load_id: int | None = None
    source: EvidenceSource = EvidenceSource.NETWORK


GA4_ID = re.compile(r"^G-[A-Z0-9]{4,}$", re.IGNORECASE)
AW_ID = re.compile(r"^AW-\d{6,}$", re.IGNORECASE)
GTM_ID = re.compile(r"^GTM-[A-Z0-9]{4,}$", re.IGNORECASE)
GT_ID = re.compile(r"^GT-[A-Z0-9]{4,}$", re.IGNORECASE)

_GA4_ITEM_KEYS = {
    "id": "item_id",
    "nm": "item_name",
    "pr": "price",
    "qt": "quantity",
    "ca": "item_category",
    "br": "item_brand",
    "va": "item_variant",
    "cp": "coupon",
    "ds": "discount",
    "af": "affiliation",
    "lp": "location_id",
}


def _num(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            f = float(v)
        except ValueError:
            return v
        return int(f) if f.is_integer() and "." not in v else f
    return v


def _host_path(url: str) -> tuple[str, str, str]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.path or "/", parts.query or ""


def _parse_body_kv(body: str | None) -> list[dict[str, str]]:
    """Form-encoded or newline-batched bodies -> list of dicts (one per line)."""
    if not body:
        return []
    lines = [ln for ln in body.replace("\r", "").split("\n") if ln.strip()]
    out = []
    for ln in lines:
        if "=" in ln and not ln.lstrip().startswith(("{", "[")):
            out.append(dict(parse_qsl(ln, keep_blank_values=True)))
    return out


def _parse_json(body: str | None) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- GA4 ----


def _ga4_item(raw: str) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for part in raw.split("~"):
        if len(part) < 2:
            continue
        key, val = part[:2], part[2:]
        if key.startswith("k") or key.startswith("v"):  # custom item params (k0/v0 ...)
            continue
        name = _GA4_ITEM_KEYS.get(key)
        if name:
            item[name] = _num(val) if name in ("price", "quantity", "discount") else val
    return item


def _ga4_events_from(common: dict[str, str], lines: list[dict[str, str]]) -> list[dict[str, Any]]:
    batches = lines or [{}]
    events = []
    for line in batches:
        merged = {**common, **line}
        if "en" not in merged:
            continue
        params: dict[str, Any] = {}
        items = []
        for k, v in merged.items():
            if k.startswith("ep."):
                params[k[3:]] = v
            elif k.startswith("epn."):
                params[k[4:]] = _num(v)
            elif re.fullmatch(r"pr\d+", k):
                items.append(_ga4_item(v))
        if "cu" in merged:
            params["currency"] = merged["cu"]
        if items:
            params["items"] = items
        events.append({"tid": merged.get("tid"), "en": merged["en"], "params": params, "dl": merged.get("dl")})
    return events


def parse_ga4(url: str, body: str | None) -> list[tuple[str | None, str, dict[str, Any]]]:
    host, path, query = _host_path(url)
    if not path.endswith("/g/collect"):
        return []
    common = dict(parse_qsl(query, keep_blank_values=True))
    tid = common.get("tid", "")
    if not GA4_ID.match(tid or ""):
        # /g/collect without a G- id is not GA4 (could be another product)
        if not any(GA4_ID.match(line.get("tid", "")) for line in _parse_body_kv(body)):
            return []
    evs = _ga4_events_from(common, _parse_body_kv(body))
    return [(e["tid"], e["en"], e["params"]) for e in evs]


# --------------------------------------------------------- Google Ads ----

_ADS_PATHS = (
    re.compile(r"^/pagead/viewthroughconversion/(\d+)/?"),
    re.compile(r"^/pagead/conversion/(\d+)/?"),
    re.compile(r"^/pagead/1p-conversion/(\d+)/?"),
)
_ADS_HOSTS = ("googleads.g.doubleclick.net", "www.googleadservices.com", "googleadservices.com", "www.google.com", "google.com")


def parse_google_ads(url: str) -> tuple[str, str, dict[str, Any], str] | None:
    host, path, query = _host_path(url)
    if host not in _ADS_HOSTS and not host.startswith("www.google."):
        return None
    for pat in _ADS_PATHS:
        m = pat.match(path)
        if m:
            q = dict(parse_qsl(query, keep_blank_values=True))
            label = q.get("label")
            params: dict[str, Any] = {"endpoint": pat.pattern.split("/")[2]}
            if label:
                params["label"] = label
            if "value" in q:
                params["value"] = _num(q["value"])
            if "currency_code" in q:
                params["currency"] = q["currency_code"]
            if "oid" in q:
                params["transaction_id"] = q["oid"]
            if "em" in q or "ecsid" in q:
                params["user_data_present"] = True
            name = "conversion" if label else "remarketing"
            return f"AW-{m.group(1)}", name, params, params["endpoint"]
    return None


# --------------------------------------------------------------- Meta ----


def parse_meta(url: str, body: str | None) -> list[tuple[str | None, str, dict[str, Any]]]:
    host, path, query = _host_path(url)
    if not (host.endswith("facebook.com") and path.rstrip("/") == "/tr"):
        return []
    rows = [dict(parse_qsl(query, keep_blank_values=True))] if query else []
    rows += _parse_body_kv(body)
    out = []
    for q in rows:
        if "ev" not in q:
            continue
        params: dict[str, Any] = {}
        for k, v in q.items():
            m = re.fullmatch(r"cd\[(.+)\]", k)
            if m:
                key = m.group(1)
                parsed = _parse_json(v) if v[:1] in "[{" else None
                params[key] = parsed if parsed is not None else _num(v) if key in ("value", "num_items") else v
        if q.get("eid"):
            params["event_id"] = q["eid"]
        out.append((q.get("id"), q["ev"], params))
    return out


# ------------------------------------------------------------- TikTok ----


def parse_tiktok(url: str, body: str | None) -> list[tuple[str | None, str, dict[str, Any], str]]:
    host, path, _ = _host_path(url)
    if not host.endswith("analytics.tiktok.com") or not path.startswith("/api/"):
        return []
    data = _parse_json(body)
    payloads = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    out: list[tuple[str | None, str, dict[str, Any], str]] = []
    for p in payloads:
        if not isinstance(p, dict):
            continue
        ctx_raw = p.get("context")
        ctx: dict[str, Any] = ctx_raw if isinstance(ctx_raw, dict) else {}
        pixel_raw = ctx.get("pixel")
        pixel: dict[str, Any] = pixel_raw if isinstance(pixel_raw, dict) else {}
        code = pixel.get("code") or p.get("pixel_code") or p.get("sdkid")
        event = p.get("event")
        props_raw = p.get("properties")
        params: dict[str, Any] = dict(props_raw) if isinstance(props_raw, dict) else {}
        if p.get("event_id"):
            params["event_id"] = p["event_id"]
        if event:
            out.append((code, str(event), params, "best_effort"))
        else:
            out.append((code, "UNPARSED", {}, "best_effort"))
    if not payloads:
        out.append((None, "UNPARSED", {}, "best_effort"))
    return out


# ----------------------------------------------------------- Snapchat ----

_SNAP_FIELD_ALIASES = {
    "pid": "pixel_id",
    "pixel_id": "pixel_id",
    "ev": "event",
    "event": "event",
    "event_type": "event",
    "e_pr": "price",
    "price": "price",
    "e_cur": "currency",
    "currency": "currency",
    "e_tid": "transaction_id",
    "transaction_id": "transaction_id",
    "e_iids": "item_ids",
    "item_ids": "item_ids",
    "e_ni": "number_items",
    "number_items": "number_items",
    "client_dedup_id": "client_dedup_id",
}


def parse_snapchat(url: str, body: str | None) -> list[tuple[str | None, str, dict[str, Any], str]]:
    host, path, query = _host_path(url)
    if not (host.startswith("tr") and host.endswith("snapchat.com")):
        return []
    rows: list[dict[str, Any]] = []
    if query:
        rows.append(dict(parse_qsl(query, keep_blank_values=True)))
    data = _parse_json(body)
    if isinstance(data, dict):
        rows.append(data)
    elif isinstance(data, list):
        rows.extend(r for r in data if isinstance(r, dict))
    else:
        rows.extend(_parse_body_kv(body))
    out: list[tuple[str | None, str, dict[str, Any], str]] = []
    for r in rows:
        norm: dict[str, Any] = {}
        for k, v in r.items():
            alias = _SNAP_FIELD_ALIASES.get(str(k).lower())
            if alias:
                norm[alias] = v
        event = norm.pop("event", None)
        pid = norm.pop("pixel_id", None)
        if "price" in norm:
            norm["price"] = _num(norm["price"])
        if isinstance(norm.get("item_ids"), str):
            s = norm["item_ids"]
            parsed = _parse_json(s)
            norm["item_ids"] = parsed if isinstance(parsed, list) else [x for x in unquote_plus(s).split(",") if x]
        if event or pid:
            out.append((pid, str(event) if event else "UNPARSED", norm, "best_effort"))
    if not out:
        out.append((None, "UNPARSED", {}, "best_effort"))
    return out


# ------------------------------------------------------------ Loaders ----


def detect_loader(url: str) -> list[tuple[str, str | None]]:
    host, path, query = _host_path(url)
    q = dict(parse_qsl(query, keep_blank_values=True))
    out: list[tuple[str, str | None]] = []
    if host.endswith("googletagmanager.com"):
        tid = q.get("id")
        if path.endswith("/gtm.js") and tid and GTM_ID.match(tid):
            out.append(("gtm", tid.upper()))
        elif path.endswith("/gtag/js") and tid:
            if GA4_ID.match(tid):
                out.append(("ga4", tid.upper()))
            elif AW_ID.match(tid):
                out.append(("google_ads", tid.upper()))
            elif GT_ID.match(tid):
                out.append(("google_tag", tid.upper()))
    elif host == "connect.facebook.net":
        m = re.search(r"/signals/config/(\d+)", path)
        if m:
            out.append(("meta", m.group(1)))
        elif path.endswith("/fbevents.js"):
            out.append(("meta", None))
    elif host.endswith("analytics.tiktok.com") and path.endswith("/pixel/events.js"):
        out.append(("tiktok", q.get("sdkid")))
    elif host.endswith("sc-static.net") and path.endswith("/scevent.min.js"):
        out.append(("snapchat", None))
    return out


# ------------------------------------------------------------- Driver ----


def parse_request(req: dict[str, Any], seq: int) -> tuple[list[PlatformEvent], list[LoaderDetection]]:
    url = str(req.get("url", ""))
    body = req.get("post_data")
    body = body if isinstance(body, str) else None
    page_url = req.get("page_url")
    step = req.get("step")
    page_load_id = req.get("page_load_id")
    events: list[PlatformEvent] = []
    loaders = [
        LoaderDetection(p, tid, url, page_url, step, page_load_id) for p, tid in detect_loader(url)
    ]

    def mk(platform: str, tid: str | None, name: str, params: dict[str, Any], conf: str = "high") -> None:
        events.append(
            PlatformEvent(
                platform=platform,
                name=name,
                tracking_id=tid,
                params=params,
                source=EvidenceSource.NETWORK,
                page_url=page_url,
                step=step,
                page_load_id=page_load_id,
                seq=seq,
                parse_confidence=conf,
                raw_url=url,
            )
        )

    for tid, name, params in parse_ga4(url, body):
        mk("ga4", tid.upper() if tid else tid, name, params)
    ads = parse_google_ads(url)
    if ads:
        tid, name, params, _endpoint = ads
        mk("google_ads", tid, name, params)
    for tid, name, params in parse_meta(url, body):
        mk("meta", tid, name, params)
    for tid, name, params, conf in parse_tiktok(url, body):
        mk("tiktok", tid, name, params, conf)
    for tid, name, params, conf in parse_snapchat(url, body):
        mk("snapchat", tid, name, params, conf)
    return events, loaders
