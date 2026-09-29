#!/usr/bin/env python3
"""nittaq-auditor command line (used by the agent following SKILL.md).

Every command prints one JSON object to stdout:
  {"text": "<Arabic message to show the user verbatim>", "state": "...", "data": {...}}
Technical logs go to stderr. Exit codes: 0 ok, 2 invalid input/observation,
3 refused (approval/gate/state), 4 internal safety stop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.browser.controller import BrowserUnavailable  # noqa: E402
from adapters.browser.detect import detect, relay_for  # noqa: E402
from core.audit.engine import AuditResult  # noqa: E402
from core.discovery.observation import ObservationError  # noqa: E402
from core.execution.gate import WriteRefused, WriteTarget  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.reporting.arabic_report import render_audit_report  # noqa: E402
from core.reporting.guard import FalseSuccessError, check_text  # noqa: E402
from core.reporting.html_report import render_html  # noqa: E402
from core.reporting.messages import t  # noqa: E402
from core.state_machine import IllegalTransition, WorkflowState  # noqa: E402
from core.workflow import Reply, Workflow  # noqa: E402

log = get_logger("nittaq.cli")


def out(payload: dict[str, Any], code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return code


def emit(reply: Reply) -> int:
    return out(reply.to_dict())


def _load_json(path: str) -> dict[str, Any]:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ObservationError(f"cannot read {path}: {exc}") from exc


# ------------------------------------------------------------------ commands
def cmd_welcome(a: argparse.Namespace) -> int:
    return out({"text": check_text(t("welcome")), "state": "IDLE", "data": {}})


def cmd_detect(a: argparse.Namespace) -> int:
    info = detect(a.agent_browser, probe=not a.no_probe)
    text = "" if info["can_verify_behaviour"] else t("browser.unavailable")
    return out({"text": text, "state": "IDLE", "data": info})


def cmd_start(a: argparse.Namespace) -> int:
    wf = Workflow.create(allow_local=a.allow_local)
    return emit(wf.start(a.text))


def cmd_reply(a: argparse.Namespace) -> int:
    return emit(Workflow.load(a.session).reply(a.text))


def cmd_collect(a: argparse.Namespace) -> int:
    """Collect an observation in-process (Playwright or static HTTP) and ingest it."""
    wf = Workflow.load(a.session)
    store = wf.data["store_url"]
    if a.adapter == "static":
        from adapters.browser.static_http import StaticHttpAdapter

        obs = StaticHttpAdapter(allow_local=bool(wf.data.get("allow_local"))).collect(store)
    else:
        from adapters.browser.flow import StorefrontFlow
        from adapters.browser.playwright_adapter import PlaywrightAdapter

        try:
            browser = PlaywrightAdapter()
        except BrowserUnavailable as exc:
            return out({"text": t("browser.unavailable"), "state": wf.machine.state.value,
                        "data": {"error": "browser_unavailable", "detail": str(exc), "fallback": "--adapter static"}}, 3)
        with browser:
            obs = StorefrontFlow(browser, a.product_url).run(store)
    if a.save_only:
        Path(a.save_only).write_text(json.dumps(obs, ensure_ascii=False, indent=2), encoding="utf-8")
        return out({"text": "", "state": wf.machine.state.value, "data": {"saved": a.save_only}})
    return _ingest(wf, obs, a.kind)


def _ingest(wf: Workflow, obs: dict[str, Any], kind: str) -> int:
    if kind == "audit":
        return emit(wf.ingest_audit(obs))
    if kind == "verify":
        return emit(wf.ingest_verification(obs))
    if kind == "merchant":
        return emit(wf.ingest_merchant(obs))
    raise ObservationError(f"unknown kind {kind}")


def cmd_ingest(a: argparse.Namespace) -> int:
    return _ingest(Workflow.load(a.session), _load_json(a.file), a.kind)


def cmd_plan(a: argparse.Namespace) -> int:
    wf = Workflow.load(a.session)
    relay = relay_for(a.agent_browser)
    if relay is None:
        return out({"text": t("browser.unavailable"), "state": wf.machine.state.value, "data": {"plan": None}}, 3)
    return out({
        "text": t("browser.agent_driven", tool=relay.tool_hint),
        "state": wf.machine.state.value,
        "data": {"plan": relay.collection_plan(a.dashboards), "skeleton": relay.observation_skeleton(wf.data["store_url"])},
    })


def cmd_pause(a: argparse.Namespace) -> int:
    extra = json.loads(a.params) if a.params else {}
    return emit(Workflow.load(a.session).pause(a.kind, a.service, **extra))


def cmd_resume(a: argparse.Namespace) -> int:
    return emit(Workflow.load(a.session).resume())


def cmd_authorize(a: argparse.Namespace) -> int:
    target = WriteTarget(page_url=a.page_url, account_label=a.account_label, resource_id=a.resource_id,
                         via=a.via, user_confirmed_target=a.user_confirmed_target)
    return emit(Workflow.load(a.session).authorize(a.proposal, target))


def cmd_record_change(a: argparse.Namespace) -> int:
    prev = json.loads(a.previous_state)
    rollback = json.loads(a.rollback) if a.rollback else None
    return emit(Workflow.load(a.session).record_change(a.token, prev, a.action_taken, a.result, rollback))


def cmd_verify_begin(a: argparse.Namespace) -> int:
    return emit(Workflow.load(a.session).begin_verification())


def cmd_fail(a: argparse.Namespace) -> int:
    return emit(Workflow.load(a.session).fail_safe(a.reason))


def cmd_status(a: argparse.Namespace) -> int:
    wf = Workflow.load(a.session)
    return out({"text": "", "state": wf.machine.state.value, "data": wf.status()})


def cmd_report(a: argparse.Namespace) -> int:
    wf = Workflow.load(a.session)
    key = {"merchant": ("merchant", "audit"), "reaudit": ("reaudit",), "audit": ("audit",)}[a.which]
    node: Any = wf.data
    for k in key:
        node = node.get(k) if isinstance(node, dict) else None
    if not node:
        return out({"text": "", "state": wf.machine.state.value, "data": {"error": "no report yet"}}, 2)
    audit = AuditResult.from_dict(node)
    text = render_audit_report(audit, "merchant.report_title" if a.which == "merchant" else "report.title")
    if a.format == "html":
        html_doc = render_html(text, t("merchant.report_title") if a.which == "merchant" else t("report.title"))
        dest = Path(a.out or f"nittaq-report-{wf.id}.html")
        dest.write_text(html_doc, encoding="utf-8")
        return out({"text": text, "state": wf.machine.state.value, "data": {"html": str(dest)}})
    if a.format == "json":
        return out({"text": text, "state": wf.machine.state.value, "data": audit.to_dict()})
    return out({"text": text, "state": wf.machine.state.value, "data": {}})


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nittaq", description="مدقق نطاق - nittaq-auditor")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("welcome").set_defaults(fn=cmd_welcome)

    d = sub.add_parser("detect")
    d.add_argument("--agent-browser", default=None, help="claude:playwright-mcp | claude:claude-in-chrome | codex:playwright-mcp | computer-use | none")
    d.add_argument("--no-probe", action="store_true")
    d.set_defaults(fn=cmd_detect)

    s = sub.add_parser("start")
    s.add_argument("--text", required=True, help="the user's invocation text, e.g. 'مدقق نطاق https://store.com'")
    s.add_argument("--allow-local", action="store_true", help="tests only: allow localhost store URLs")
    s.set_defaults(fn=cmd_start)

    r = sub.add_parser("reply")
    r.add_argument("--session", required=True)
    r.add_argument("--text", required=True)
    r.set_defaults(fn=cmd_reply)

    c = sub.add_parser("collect")
    c.add_argument("--session", required=True)
    c.add_argument("--adapter", choices=("playwright", "static"), default="playwright")
    c.add_argument("--kind", choices=("audit", "verify"), default="audit")
    c.add_argument("--product-url", default=None)
    c.add_argument("--save-only", default=None, help="write the observation to a file instead of ingesting")
    c.set_defaults(fn=cmd_collect)

    i = sub.add_parser("ingest")
    i.add_argument("--session", required=True)
    i.add_argument("--file", required=True)
    i.add_argument("--kind", choices=("audit", "verify", "merchant"), default="audit")
    i.set_defaults(fn=cmd_ingest)

    pl = sub.add_parser("plan")
    pl.add_argument("--session", required=True)
    pl.add_argument("--agent-browser", required=True)
    pl.add_argument("--dashboards", action="store_true")
    pl.set_defaults(fn=cmd_plan)

    pa = sub.add_parser("pause")
    pa.add_argument("--session", required=True)
    pa.add_argument("--kind", required=True, choices=("auth_required", "session_expired", "captcha", "two_factor", "multiple_accounts",
                                                      "unexpected_ui", "permission_denied", "customer_login"))
    pa.add_argument("--service", required=True)
    pa.add_argument("--params", default=None, help='JSON, e.g. {"accounts": "A, B"}')
    pa.set_defaults(fn=cmd_pause)

    re_ = sub.add_parser("resume")
    re_.add_argument("--session", required=True)
    re_.set_defaults(fn=cmd_resume)

    au = sub.add_parser("authorize")
    au.add_argument("--session", required=True)
    au.add_argument("--proposal", required=True)
    au.add_argument("--page-url", required=True, help="URL currently open in the browser (read from the page)")
    au.add_argument("--resource-id", default=None, help="property/container/pixel/account id visible on the page")
    au.add_argument("--account-label", default=None)
    au.add_argument("--via", default=None, help="'salla' when the change is made in the Salla dashboard")
    au.add_argument("--user-confirmed-target", action="store_true", help="only after the user confirmed this exact target in chat")
    au.set_defaults(fn=cmd_authorize)

    rc = sub.add_parser("record-change")
    rc.add_argument("--session", required=True)
    rc.add_argument("--token", required=True)
    rc.add_argument("--previous-state", required=True, help='JSON: {"captured": true, ...} or {"captured": false, "reason": "..."}')
    rc.add_argument("--action-taken", required=True)
    rc.add_argument("--result", required=True, choices=("applied", "failed", "partial", "not_applied"))
    rc.add_argument("--rollback", default=None, help='JSON: {"possible": true, "how": "..."}')
    rc.set_defaults(fn=cmd_record_change)

    vb = sub.add_parser("verify-begin")
    vb.add_argument("--session", required=True)
    vb.set_defaults(fn=cmd_verify_begin)

    f = sub.add_parser("fail")
    f.add_argument("--session", required=True)
    f.add_argument("--reason", required=True, help="Arabic explanation shown to the user")
    f.set_defaults(fn=cmd_fail)

    st = sub.add_parser("status")
    st.add_argument("--session", required=True)
    st.set_defaults(fn=cmd_status)

    rp = sub.add_parser("report")
    rp.add_argument("--session", required=True)
    rp.add_argument("--which", choices=("audit", "reaudit", "merchant"), default="audit")
    rp.add_argument("--format", choices=("text", "json", "html"), default="text")
    rp.add_argument("--out", default=None)
    rp.set_defaults(fn=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except IllegalTransition as exc:
        return out({"text": t("errors.illegal_step", state=exc.current.value), "state": exc.current.value,
                    "data": {"error": "illegal_transition", "detail": str(exc)}}, 3)
    except WriteRefused as exc:
        return out({"text": exc.detail or t("execution.refused.not_approved"), "state": WorkflowState.EXECUTING.value,
                    "data": {"error": "write_refused", "code": exc.code}}, 3)
    except FalseSuccessError as exc:  # before ValueError: it is a subclass
        log.error("false-success guard tripped: %s", exc)
        return out({"text": t("errors.internal"), "state": "", "data": {"error": "false_success_guard", "detail": str(exc)}}, 4)
    except (ObservationError, ValueError, KeyError, FileNotFoundError) as exc:
        log.warning("invalid input: %s", exc)
        return out({"text": t("errors.observation_invalid"), "state": "", "data": {"error": "invalid_input", "detail": str(exc)}}, 2)
    except PermissionError as exc:
        return out({"text": t("execution.refused.not_approved"), "state": "", "data": {"error": "refused", "detail": str(exc)}}, 3)


if __name__ == "__main__":
    sys.exit(main())
