"""Browser abstraction: capability detection, safety policy, static fallback, relay plans (spec §11-12, §44)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.browser.controller import Capabilities, Locator, SafetyPolicy, UnsafeAction
from adapters.browser.detect import detect, relay_for
from adapters.browser.static_http import StaticHttpAdapter
from core.audit.engine import run_audit
from core.models import ServiceStatus
from tests.fixtures.fake_store import FakeStore

ROOT = Path(__file__).resolve().parents[2]


class SafetyPolicyTests(unittest.TestCase):
    def test_payment_controls_forbidden(self) -> None:
        for label in ("ادفع الآن", "إتمام الدفع", "تأكيد الطلب", "Place order", "Pay now", "PAY"):
            with self.subTest(label=label):
                self.assertTrue(SafetyPolicy.is_forbidden_label(label))
                with self.assertRaises(UnsafeAction):
                    SafetyPolicy.check_click(Locator(role="button", name=label))

    def test_safe_controls_allowed(self) -> None:
        for label in ("إضافة للسلة", "إتمام الطلب", "Add to cart", "PayPal info", "عرض السلة"):
            with self.subTest(label=label):
                self.assertFalse(SafetyPolicy.is_forbidden_label(label))

    def test_challenge_detection(self) -> None:
        self.assertEqual(SafetyPolicy.classify_blocker("<title>Just a moment...</title>", "https://s.com/"), "captcha")
        self.assertEqual(SafetyPolicy.classify_blocker("<html></html>", "https://accounts.example.com/login"), "auth_required")
        # background recaptcha scripts on normal pages are NOT a blocker
        self.assertIsNone(SafetyPolicy.classify_blocker("<script src='https://www.google.com/recaptcha/api.js'></script>", "https://s.com/"))

    def test_no_typing_api(self) -> None:
        from adapters.browser.controller import BrowserController

        for name in ("fill", "type", "type_text", "press", "set_input"):
            self.assertFalse(hasattr(BrowserController, name), name)


class DetectionTests(unittest.TestCase):
    def test_browser_unavailable_is_reported_truthfully(self) -> None:
        with mock.patch("adapters.browser.detect.probe_playwright", return_value={"available": False, "reason": "not installed"}):
            info = detect(None)
        self.assertEqual(info["recommended"], "static-http")
        self.assertFalse(info["can_verify_behaviour"])
        self.assertFalse(info["dashboards_possible"])

    def test_agent_declared_browser(self) -> None:
        info = detect("claude:playwright-mcp", probe=False)
        self.assertEqual(info["recommended"], "claude:playwright-mcp")
        self.assertTrue(info["dashboards_possible"])

    def test_computer_use_cannot_capture_network(self) -> None:
        r = relay_for("computer-use")
        self.assertFalse(r.capabilities().network_capture)
        plan = r.collection_plan()
        self.assertIn("cannot capture network", plan[0])

    def test_unknown_agent_browser_rejected(self) -> None:
        with self.assertRaises(ValueError):
            relay_for("magic-browser")

    def test_relay_skeleton_is_valid_observation(self) -> None:
        from core.discovery.observation import validate_observation

        sk = relay_for("codex:playwright-mcp").observation_skeleton("https://s.example.com/")
        self.assertEqual(validate_observation(sk), [])
        self.assertTrue(relay_for("claude:claude-in-chrome").collection_plan(include_dashboards=True))

    def test_agent_events_without_network_capture_not_verified(self) -> None:
        sk = relay_for("computer-use").observation_skeleton("https://store.example.com/")
        sk["pages"] = [{"url": "https://store.example.com/", "step": "home"}, {"url": "https://store.example.com/p/p1234567", "step": "view_item"},
                       {"url": "https://store.example.com/p/p1234567", "step": "add_to_cart"}]
        sk["captured_events"] = [
            {"platform": "meta", "name": n, "tracking_id": "1", "step": s, "params": {"content_ids": ["A"], "content_type": "product", "value": 1, "currency": "SAR"},
             "evidence_note": "Meta Pixel Helper panel"} for n, s in (("PageView", "home"), ("ViewContent", "view_item"), ("AddToCart", "add_to_cart"))
        ]
        r = run_audit(sk, ["meta"]).results["meta"]
        self.assertEqual(r.status, ServiceStatus.PARTIALLY_VERIFIED)

    def test_captured_events_require_evidence_note(self) -> None:
        from core.discovery.observation import validate_observation

        sk = relay_for("computer-use").observation_skeleton("https://s.example.com/")
        sk["captured_events"] = [{"platform": "meta", "name": "Purchase"}]
        self.assertTrue(validate_observation(sk))

    def test_capabilities_dict(self) -> None:
        self.assertEqual(Capabilities(True, False, True).to_dict(), {"javascript": True, "network_capture": False, "interaction": True})


class StaticAdapterTests(unittest.TestCase):
    def test_static_collection_against_local_store(self) -> None:
        with FakeStore("ok") as store:
            obs = StaticHttpAdapter(allow_local=True).collect(store.url)
        self.assertEqual(obs["capabilities"], {"javascript": False, "network_capture": False, "interaction": False})
        self.assertEqual(obs["flow"]["completed"], ["home", "view_item"])
        a = run_audit(obs)
        self.assertEqual(a.results["ga4"].status, ServiceStatus.DETECTED)
        self.assertEqual(a.results["meta"].status, ServiceStatus.DETECTED)
        self.assertEqual(a.results["tiktok"].status, ServiceStatus.UNABLE_TO_VERIFY)
        self.assertTrue(a.context["is_salla"])

    def test_private_hosts_refused_by_default(self) -> None:
        res = StaticHttpAdapter().fetch("http://127.0.0.1:9/")
        self.assertEqual(res["status"], "blocked")

    def test_unreachable_host(self) -> None:
        res = StaticHttpAdapter(timeout=2, allow_local=True).fetch("http://127.0.0.1:9/")
        self.assertIn(res["status"], ("error", "timeout"))


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str, env: dict | None = None) -> tuple[int, dict]:
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "nittaq.py"), *args], capture_output=True, text=True, env=env)
        return p.returncode, json.loads(p.stdout)

    def test_cli_audit_only_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "NITTAQ_HOME": tmp}
            code, out = self.run_cli("welcome", env=env)
            self.assertEqual(code, 0)
            self.assertIn("مدقق نطاق", out["text"])
            code, out = self.run_cli("start", "--text", "مدقق نطاق https://store.example.com", env=env)
            sid = out["data"]["session"]
            obs = Path(tmp) / "o.json"
            from tests.fixtures.builders import healthy_funnel

            obs.write_text(json.dumps(healthy_funnel().build()), encoding="utf-8")
            code, out = self.run_cli("ingest", "--session", sid, "--file", str(obs), env=env)
            self.assertEqual((code, out["state"]), (0, "WAITING_FOR_APPROVAL"))
            code, out = self.run_cli("authorize", "--session", sid, "--proposal", "P1", "--page-url", "https://analytics.google.com/", env=env)
            self.assertEqual(code, 3)
            self.assertEqual(out["data"]["code"], "not_in_execution_state")
            code, out = self.run_cli("verify-begin", "--session", sid, env=env)
            self.assertEqual(out["data"]["error"], "illegal_transition")
            code, out = self.run_cli("report", "--session", sid, "--format", "html", "--out", str(Path(tmp) / "r.html"), env=env)
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "r.html").exists())

    def test_cli_invalid_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "NITTAQ_HOME": tmp}
            _, out = self.run_cli("start", "--text", "مدقق نطاق https://store.example.com", env=env)
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"schema_version": 1}', encoding="utf-8")
            code, out = self.run_cli("ingest", "--session", out["data"]["session"], "--file", str(bad), env=env)
            self.assertEqual(code, 2)
            self.assertEqual(out["data"]["error"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
