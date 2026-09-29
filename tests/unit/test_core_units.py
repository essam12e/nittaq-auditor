"""Unit tests: invocation, network decoding, state machine, knowledge, logging."""

from __future__ import annotations

import json
import unittest
from datetime import date

from core.discovery.network_parser import parse_request
from core.discovery.salla import classify_page, is_salla_store
from core.invocation import (
    INTENT_AUDIT,
    INTENT_REPAIR,
    INTENT_VERIFY,
    INTENT_WELCOME,
    InvalidStoreUrl,
    normalize_store_url,
    parse_invocation,
)
from core.knowledge import load_rules, validate_rules_doc
from core.logging_utils import REDACTED, redact, redact_text
from core.state_machine import TRANSITIONS, IllegalTransition, WorkflowMachine, WorkflowState

S = WorkflowState


class InvocationTests(unittest.TestCase):
    def test_trigger_only(self) -> None:
        r = parse_invocation("مدقق نطاق")
        self.assertTrue(r.triggered)
        self.assertEqual(r.intent, INTENT_WELCOME)
        self.assertIsNone(r.store_url)

    def test_trigger_with_diacritics_and_tatweel(self) -> None:
        self.assertTrue(parse_invocation("مُدقّق نـطاق").triggered)

    def test_not_triggered(self) -> None:
        self.assertFalse(parse_invocation("افحص متجري").triggered)

    def test_with_url(self) -> None:
        r = parse_invocation("مدقق نطاق https://Example.com/ar")
        self.assertEqual((r.intent, r.store_url), (INTENT_AUDIT, "https://example.com/ar"))

    def test_bare_domain(self) -> None:
        self.assertEqual(parse_invocation("مدقق نطاق mystore.sa").store_url, "https://mystore.sa/")

    def test_salla_subpath_store(self) -> None:
        self.assertEqual(parse_invocation("مدقق نطاق salla.sa/my-store").store_url, "https://salla.sa/my-store")

    def test_focus_services(self) -> None:
        cases = {
            "مدقق نطاق افحص جوجل": ["ga4", "gtm", "google_ads"],
            "مدقق نطاق افحص البيكسلات": ["meta", "tiktok", "snapchat"],
            "مدقق نطاق افحص Meta": ["meta"],
            "مدقق نطاق افحص TikTok": ["tiktok"],
            "مدقق نطاق افحص Snapchat": ["snapchat"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_invocation(text).focus_services, expected)

    def test_merchant_request(self) -> None:
        r = parse_invocation("مدقق نطاق افحص Merchant")
        self.assertTrue(r.merchant_requested)
        self.assertEqual(r.focus_services, [])

    def test_repair_and_verify_intents(self) -> None:
        self.assertEqual(parse_invocation("مدقق نطاق اصلح مشاكل التتبع").intent, INTENT_REPAIR)
        self.assertEqual(parse_invocation("مدقق نطاق تأكد من الربط").intent, INTENT_VERIFY)
        self.assertEqual(parse_invocation("مدقق نطاق افحص متجري").intent, INTENT_AUDIT)

    def test_rejects_credentials_and_private_hosts(self) -> None:
        with self.assertRaises(InvalidStoreUrl):
            normalize_store_url("https://user:pass@example.com")
        with self.assertRaises(InvalidStoreUrl):
            normalize_store_url("http://127.0.0.1:8000")
        with self.assertRaises(InvalidStoreUrl):
            normalize_store_url("ftp://example.com")
        self.assertEqual(parse_invocation("مدقق نطاق http://10.0.0.5/").url_error, None)  # not matched as public URL
        self.assertTrue(normalize_store_url("http://127.0.0.1:8000", allow_local=True).startswith("http://127.0.0.1"))


class NetworkParserTests(unittest.TestCase):
    def one(self, url: str, body: str | None = None):
        evs, lds = parse_request({"url": url, "post_data": body, "step": "view_item", "page_load_id": 1}, 0)
        return evs, lds

    def test_ga4_batched_body(self) -> None:
        evs, _ = self.one("https://region1.google-analytics.com/g/collect?v=2&tid=G-ABC1234567&cu=SAR",
                          "en=view_item&epn.value=10&pr1=idA~nmX~pr10~qt2\nen=add_to_cart&ep.transaction_id=T1")
        self.assertEqual([e.name for e in evs], ["view_item", "add_to_cart"])
        self.assertEqual(evs[0].params["items"][0], {"item_id": "A", "item_name": "X", "price": 10, "quantity": 2})
        self.assertEqual(evs[0].params["currency"], "SAR")
        self.assertEqual(evs[1].params["transaction_id"], "T1")

    def test_non_ga4_collect_ignored(self) -> None:
        evs, _ = self.one("https://example.com/g/collect?tid=UA-1&en=x")
        self.assertEqual(evs, [])

    def test_google_ads_conversion(self) -> None:
        evs, _ = self.one("https://googleads.g.doubleclick.net/pagead/viewthroughconversion/123456789/?label=abc&value=10.5&currency_code=SAR&oid=O1")
        e = evs[0]
        self.assertEqual((e.platform, e.tracking_id, e.name), ("google_ads", "AW-123456789", "conversion"))
        self.assertEqual(e.params["value"], 10.5)
        self.assertEqual(e.params["transaction_id"], "O1")

    def test_meta_hit(self) -> None:
        evs, _ = self.one("https://www.facebook.com/tr/?id=42&ev=Purchase&cd[value]=9&cd[currency]=SAR&cd[content_ids]=%5B%22A%22%5D&eid=e1")
        e = evs[0]
        self.assertEqual((e.name, e.tracking_id), ("Purchase", "42"))
        self.assertEqual(e.params, {"value": 9, "currency": "SAR", "content_ids": ["A"], "event_id": "e1"})

    def test_tiktok_and_snap_best_effort(self) -> None:
        evs, _ = self.one("https://analytics.tiktok.com/api/v2/pixel", json.dumps({"event": "AddToCart", "context": {"pixel": {"code": "C1"}}, "properties": {"value": 1}}))
        self.assertEqual((evs[0].name, evs[0].tracking_id, evs[0].parse_confidence), ("AddToCart", "C1", "best_effort"))
        evs, _ = self.one("https://tr.snapchat.com/p", "garbage")
        self.assertEqual(evs[0].name, "UNPARSED")

    def test_loaders(self) -> None:
        cases = {
            "https://www.googletagmanager.com/gtm.js?id=GTM-AB12CD": ("gtm", "GTM-AB12CD"),
            "https://www.googletagmanager.com/gtag/js?id=G-ABC1234567": ("ga4", "G-ABC1234567"),
            "https://www.googletagmanager.com/gtag/js?id=AW-123456789": ("google_ads", "AW-123456789"),
            "https://connect.facebook.net/signals/config/777": ("meta", "777"),
            "https://analytics.tiktok.com/i18n/pixel/events.js?sdkid=C9": ("tiktok", "C9"),
            "https://sc-static.net/scevent.min.js": ("snapchat", None),
        }
        for url, (platform, tid) in cases.items():
            with self.subTest(url=url):
                _, lds = self.one(url)
                self.assertEqual((lds[0].platform, lds[0].tracking_id), (platform, tid))


class SallaTests(unittest.TestCase):
    def test_page_classification_hints(self) -> None:
        self.assertEqual(classify_page("https://s.com/"), "home")
        self.assertEqual(classify_page("https://s.com/ar/shirt/p1234567"), "view_item")
        self.assertEqual(classify_page("https://s.com/cart"), "view_cart")
        self.assertIsNone(classify_page("https://s.com/blog/post"))

    def test_salla_detection(self) -> None:
        self.assertTrue(is_salla_store(["cdn.salla.network"])[0])
        self.assertFalse(is_salla_store(["cdn.salla.sa"])[0])  # weak marker alone is not enough
        self.assertFalse(is_salla_store([])[0])


class StateMachineTests(unittest.TestCase):
    def test_no_direct_path_to_execution(self) -> None:
        allowed_sources = {s for s, targets in TRANSITIONS.items() if S.EXECUTING in targets}
        self.assertEqual(allowed_sources, {S.WAITING_FOR_APPROVAL, S.MERCHANT_WRITE_APPROVAL_REQUIRED, S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED})

    def test_execution_must_verify(self) -> None:
        self.assertNotIn(S.COMPLETED, TRANSITIONS[S.EXECUTING])
        self.assertNotIn(S.PARTIALLY_COMPLETED, TRANSITIONS[S.EXECUTING])

    def test_merchant_inspection_precedes_merchant_write(self) -> None:
        self.assertNotIn(S.MERCHANT_WRITE_APPROVAL_REQUIRED, TRANSITIONS[S.MERCHANT_APPROVAL_REQUIRED])
        self.assertIn(S.MERCHANT_INSPECTING, TRANSITIONS[S.MERCHANT_APPROVAL_REQUIRED])

    def test_illegal_transition(self) -> None:
        m = WorkflowMachine()
        with self.assertRaises(IllegalTransition):
            m.transition(S.EXECUTING)

    def test_resume_returns_to_paused_state_only(self) -> None:
        m = WorkflowMachine()
        m.transition(S.DISCOVERING)
        m.transition(S.AUTH_REQUIRED)
        with self.assertRaises(IllegalTransition):
            m.transition(S.EXECUTING)  # can't use a login pause to jump to execution
        self.assertEqual(m.resume(), S.DISCOVERING)

    def test_every_state_has_transitions(self) -> None:
        self.assertEqual(set(TRANSITIONS), set(S))


class KnowledgeTests(unittest.TestCase):
    def test_rules_valid_and_sourced(self) -> None:
        rules = load_rules()
        self.assertGreater(len(rules), 25)
        for r in rules.values():
            self.assertTrue(r.source_urls)
            self.assertTrue(all(u.startswith("https://") for u in r.source_urls))

    def test_stale_rules_warned(self) -> None:
        doc = json.loads((__import__("core.knowledge", fromlist=["RULES_PATH"]).RULES_PATH).read_text(encoding="utf-8"))
        errors, warnings = validate_rules_doc(doc, today=date(2030, 1, 1))
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_non_official_source_rejected(self) -> None:
        doc = {"rules": [{"id": "x", "platform": "ga4", "title": "t", "statement": "s", "requirement_level": "required",
                          "source_urls": ["https://someblog.example.com/post"], "date_checked": "2026-09-29",
                          "verification_method": "web_search_excerpt", "confidence": "confirmed", "validators": ["ga4"]}]}
        errors, _ = validate_rules_doc(doc, today=date(2026, 9, 29))
        self.assertTrue(any("official" in e for e in errors))

    def test_every_rule_id_cited_in_code_exists(self) -> None:
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        cited = set()
        for p in list((root / "validators").rglob("*.py")) + list((root / "core").rglob("*.py")):
            cited |= set(re.findall(r'rule_id="([a-z0-9_.]+)"', p.read_text(encoding="utf-8")))
            cited |= set(re.findall(r'rule_id=\("([a-z0-9_.]+)"', p.read_text(encoding="utf-8")))
        missing = cited - set(load_rules())
        self.assertEqual(missing, set())


class LoggingTests(unittest.TestCase):
    def test_redact_text(self) -> None:
        s = redact_text("url?password=abc&otp=1234&access_token=xyz&ev=Purchase Authorization: Bearer abc.def")
        for secret in ("abc&", "1234", "xyz"):
            self.assertNotIn(secret, s)
        self.assertIn("ev=Purchase", s)

    def test_redact_structures(self) -> None:
        d = redact({"password": "p", "headers": {"Cookie": "c"}, "event_id": "keep", "transaction_id": "T1", "nested": [{"otp": "1"}]})
        self.assertEqual(d["password"], REDACTED)
        self.assertEqual(d["headers"]["Cookie"], REDACTED)
        self.assertEqual(d["event_id"], "keep")
        self.assertEqual(d["transaction_id"], "T1")
        self.assertEqual(d["nested"][0]["otp"], REDACTED)


if __name__ == "__main__":
    unittest.main()
