"""End-to-end workflow tests through the orchestrator (spec §5, §43, §49)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.execution.gate import WriteRefused, WriteTarget
from core.reporting.guard import violations
from core.state_machine import IllegalTransition, WorkflowState
from core.workflow import Workflow
from tests.fixtures.builders import Obs, full_ga4, healthy_funnel

S = WorkflowState


def issue_obs() -> Obs:
    """GA4 with a currency problem, Meta duplicate, TikTok missing."""
    o = healthy_funnel()
    o.gtag_loader().ga4_pageview().ga4("view_item", "view_item", currency="USD").ga4("add_to_cart", "add_to_cart")
    o.meta("PageView", "home").meta("ViewContent", "view_item", content_ids=["SKU1"], content_type="product")
    for _ in range(2):
        o.meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
    return o


def fixed_obs() -> Obs:
    o = healthy_funnel()
    full_ga4(o)
    o.meta("PageView", "home").meta("ViewContent", "view_item", content_ids=["SKU1"], content_type="product")
    o.meta("AddToCart", "add_to_cart", value=100, currency="SAR", content_ids=["SKU1"], content_type="product")
    o.d["collected_at"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    return o


def merchant_obs() -> dict:
    o = Obs(adapter="claude:playwright-mcp").page("view_item")
    o.dashboard("merchant", status="ok", account_id="555", website_url="https://store.example.com", website_claimed=True,
                products=[{"offer_id": "A", "status": "disapproved", "issues": [{"description": "Mismatched value (page crawl) [price]"}]}])
    return o.build()


class WorkflowTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("NITTAQ_HOME")
        os.environ["NITTAQ_HOME"] = self.tmp.name

    def tearDown(self) -> None:
        if self.old is None:
            os.environ.pop("NITTAQ_HOME", None)
        else:
            os.environ["NITTAQ_HOME"] = self.old
        self.tmp.cleanup()

    def started(self, obs: Obs | None = None) -> Workflow:
        wf = Workflow.create()
        wf.start("مدقق نطاق https://store.example.com")
        if obs is not None:
            wf.ingest_audit(obs.build())
        return wf

    def ga4_target(self) -> WriteTarget:
        return WriteTarget(page_url="https://analytics.google.com/analytics/web/", resource_id="G-ABC1234567")


class InvocationFlow(WorkflowTestBase):
    def test_trigger_only_shows_welcome_and_waits(self) -> None:
        wf = Workflow.create()
        r = wf.start("مدقق نطاق")
        self.assertEqual(r.state, "WAITING_FOR_STORE")
        self.assertIn("مرحبًا بك في مدقق نطاق", r.text)
        self.assertIn("لا يجري أي تعديل", r.text)
        r2 = wf.reply("https://store.example.com")
        self.assertEqual(r2.state, "DISCOVERING")

    def test_url_in_invocation_starts_immediately(self) -> None:
        r = Workflow.create().start("مدقق نطاق https://store.example.com")
        self.assertEqual(r.state, "DISCOVERING")
        self.assertEqual(r.data["store_url"], "https://store.example.com/")

    def test_focus_services(self) -> None:
        wf = Workflow.create()
        r = wf.start("مدقق نطاق افحص Meta https://store.example.com")
        self.assertEqual(r.data["focus_services"], ["meta"])
        r2 = wf.ingest_audit(issue_obs().build())
        self.assertEqual(list(r2.data["audit"]["results"]), ["meta"])

    def test_observation_for_other_store_rejected(self) -> None:
        wf = self.started()
        o = issue_obs()
        o.d["store_url"] = "https://other.example.org/"
        with self.assertRaises(ValueError):
            wf.ingest_audit(o.build())


class AuditOnly(WorkflowTestBase):
    def test_audit_makes_no_changes_and_asks(self) -> None:
        wf = self.started(issue_obs())
        self.assertEqual(wf.machine.state, S.WAITING_FOR_APPROVAL)
        self.assertEqual(wf.changes, [])
        self.assertEqual(wf.data["authorizations"], [])
        self.assertTrue(all(p.status == "proposed" for p in wf.proposals))

    def test_finding_problem_does_not_repair_and_missing_does_not_connect(self) -> None:
        wf = self.started(issue_obs())
        tiktok = next(p for p in wf.proposals if p.service == "tiktok")
        self.assertEqual(tiktok.action, "tiktok.connect")
        with self.assertRaises(WriteRefused) as cm:
            wf.authorize(tiktok.id, WriteTarget(page_url="https://ads.tiktok.com/", user_confirmed_target=True))
        self.assertIn(cm.exception.code, ("not_in_execution_state",))

    def test_cannot_jump_from_report_to_execution(self) -> None:
        wf = self.started(issue_obs())
        with self.assertRaises(IllegalTransition):
            wf.record_change("x", {"captured": True}, "x", "applied")
        with self.assertRaises(IllegalTransition):
            wf.begin_verification()

    def test_report_never_claims_unscoped_success(self) -> None:
        wf = self.started(healthy_funnel())
        state_text = json.dumps(wf.data, ensure_ascii=False)
        self.assertEqual(violations(state_text), [])


class ApprovalFlow(WorkflowTestBase):
    def test_refusal_stops_cleanly(self) -> None:
        wf = self.started(issue_obs())
        r = wf.reply("لا")
        self.assertEqual(r.state, "MERCHANT_APPROVAL_REQUIRED")
        self.assertTrue(all(p.status == "rejected" for p in wf.proposals))
        r = wf.reply("لا")
        self.assertIn(r.state, ("COMPLETED", "PARTIALLY_COMPLETED"))
        self.assertEqual(wf.changes, [])

    def test_ambiguous_reply_asks_again(self) -> None:
        wf = self.started(issue_obs())
        r = wf.reply("ممكن، خلني افكر")
        self.assertEqual(r.state, "WAITING_FOR_APPROVAL")
        self.assertEqual(wf.ledger.approved_proposals, [])

    def test_scoped_approval_and_execution_gate(self) -> None:
        wf = self.started(issue_obs())
        ga = next(p for p in wf.proposals if p.service == "ga4")
        meta = next(p for p in wf.proposals if p.service == "meta")
        r = wf.reply(f"موافق على {ga.id} فقط")
        self.assertEqual(r.state, "EXECUTING")
        with self.assertRaises(WriteRefused):
            wf.authorize(meta.id, WriteTarget(page_url="https://business.facebook.com/", resource_id="1234567890"))
        tok = wf.authorize(ga.id, self.ga4_target()).data["authorization"]["token"]
        wf.record_change(tok, {"captured": True, "currency": "USD"}, "set currency source", "applied",
                         {"possible": True, "how": "restore previous currency setting"})
        with self.assertRaises(WriteRefused):  # token is single-use
            wf.record_change(tok, {"captured": True}, "again", "applied")
        wf.begin_verification()
        time.sleep(0.01)
        r = wf.ingest_verification(fixed_obs().build())
        self.assertEqual(r.state, "MERCHANT_APPROVAL_REQUIRED")
        self.assertEqual(wf.changes[0].verification_result, "verified")
        self.assertIn("✓ تم التحقق من الربط ضمن الاختبارات التي تم تنفيذها", r.text)

    def test_destructive_requires_explicit_confirmation(self) -> None:
        wf = self.started(issue_obs())
        meta = next(p for p in wf.proposals if p.service == "meta")
        self.assertTrue(meta.destructive)
        r = wf.reply(f"موافق على {meta.id}")
        self.assertEqual(r.state, "WAITING_FOR_APPROVAL")
        self.assertEqual(r.data["pending"], [meta.id])
        r = wf.reply("تمام")  # not an explicit confirmation
        self.assertEqual(r.state, "WAITING_FOR_APPROVAL")
        r = wf.reply(f"أؤكد {meta.id}")
        self.assertEqual(r.state, "EXECUTING")
        self.assertIn(meta.id, wf.ledger.destructive_confirmed)

    def test_confirmation_word_inside_other_words_is_not_confirmation(self) -> None:
        wf = self.started(issue_obs())
        meta = next(p for p in wf.proposals if p.service == "meta")
        wf.reply(f"موافق على {meta.id}")
        r = wf.reply("سأتأكد لاحقا")  # contains "تاكد" but is not "أؤكد"
        self.assertEqual(r.state, "WAITING_FOR_APPROVAL")
        self.assertNotIn(meta.id, wf.ledger.destructive_confirmed)

    def test_rejecting_destructive_withdraws_approval(self) -> None:
        wf = self.started(issue_obs())
        meta = next(p for p in wf.proposals if p.service == "meta")
        wf.reply(f"موافق على {meta.id}")
        r = wf.reply("لا")
        self.assertNotIn(meta.id, wf.ledger.approved_proposals)
        self.assertEqual(r.state, "MERCHANT_APPROVAL_REQUIRED")

    def test_failed_verification_is_not_success(self) -> None:
        wf = self.started(issue_obs())
        ga = next(p for p in wf.proposals if p.service == "ga4")
        wf.reply(f"موافق على {ga.id}")
        tok = wf.authorize(ga.id, self.ga4_target()).data["authorization"]["token"]
        wf.record_change(tok, {"captured": False, "reason": "setting not visible"}, "changed currency", "applied")
        wf.begin_verification()
        still_broken = issue_obs()
        still_broken.d["collected_at"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        r = wf.ingest_verification(still_broken.build())
        self.assertEqual(wf.changes[0].verification_result, "failed")
        self.assertIn("لن أعتبر الربط مكتملًا حتى يتم التحقق", r.text)
        self.assertNotIn("تم التحقق من الربط ضمن", r.text.split("تقرير إعادة الفحص الشامل")[0])

    def test_stale_verification_evidence_rejected(self) -> None:
        wf = self.started(issue_obs())
        ga = next(p for p in wf.proposals if p.service == "ga4")
        wf.reply(f"موافق على {ga.id}")
        tok = wf.authorize(ga.id, self.ga4_target()).data["authorization"]["token"]
        wf.record_change(tok, {"captured": True}, "x", "applied")
        wf.begin_verification()
        old = fixed_obs()
        old.d["collected_at"] = "2020-01-01T00:00:00+00:00"
        r = wf.ingest_verification(old.build())
        self.assertEqual(r.state, "VERIFYING")
        self.assertEqual(wf.changes[0].verification_result, "pending")

    def test_unable_to_verify_after_change(self) -> None:
        wf = self.started(issue_obs())
        ga = next(p for p in wf.proposals if p.service == "ga4")
        wf.reply(f"موافق على {ga.id}")
        tok = wf.authorize(ga.id, self.ga4_target()).data["authorization"]["token"]
        wf.record_change(tok, {"captured": True}, "x", "applied")
        wf.begin_verification()
        static = Obs(behavioral=False).page("home", "<script src='https://www.googletagmanager.com/gtag/js?id=G-ABC1234567'></script>")
        static.d["collected_at"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        r = wf.ingest_verification(static.build())
        self.assertEqual(wf.changes[0].verification_result, "unable_to_verify")
        self.assertIn("لم أتمكن من التحقق بشكل قاطع", r.text)


class MerchantFlow(WorkflowTestBase):
    def to_merchant_gate(self) -> Workflow:
        wf = self.started(issue_obs())
        wf.reply("لا")
        self.assertEqual(wf.machine.state, S.MERCHANT_APPROVAL_REQUIRED)
        return wf

    def test_merchant_is_last_and_separate(self) -> None:
        wf = self.started(issue_obs())
        self.assertFalse(any(p.merchant for p in wf.proposals))
        r = wf.reply("نعم")  # approves tracking offer only
        self.assertFalse(wf.ledger.merchant_inspection)
        self.assertNotIn("merchant", " ".join(p.service for p in wf.proposals if p.status == "approved"))
        self.assertEqual(r.state, "WAITING_FOR_APPROVAL")  # destructive confirmation pending

    def test_user_refuses_merchant_inspection(self) -> None:
        wf = self.to_merchant_gate()
        r = wf.reply("لا")
        self.assertIn(r.state, ("COMPLETED", "PARTIALLY_COMPLETED"))
        self.assertTrue(wf.ledger.merchant_inspection_refused)
        with self.assertRaises(IllegalTransition):
            wf.ingest_merchant(merchant_obs())

    def test_merchant_ingest_requires_inspection_approval(self) -> None:
        wf = self.to_merchant_gate()
        with self.assertRaises(IllegalTransition):
            wf.ingest_merchant(merchant_obs())

    def test_inspection_approval_does_not_allow_modification(self) -> None:
        wf = self.to_merchant_gate()
        r = wf.reply("نعم")
        self.assertEqual(r.state, "MERCHANT_INSPECTING")
        r = wf.ingest_merchant(merchant_obs())
        self.assertEqual(r.state, "MERCHANT_WRITE_APPROVAL_REQUIRED")
        m1 = next(p for p in wf.proposals if p.merchant)
        self.assertIn("هل توافق على تنفيذ هذه التغييرات في Merchant Center", r.text)
        with self.assertRaises(WriteRefused) as cm:
            wf.authorize(m1.id, WriteTarget(page_url="https://merchants.google.com/mc/", resource_id="555"))
        self.assertEqual(cm.exception.code, "not_in_execution_state")
        r = wf.reply("لا")
        self.assertIn(r.state, ("COMPLETED", "PARTIALLY_COMPLETED"))
        self.assertIn("لن يتم إجراء أي تعديل على Merchant Center", r.text)

    def test_merchant_write_after_second_approval(self) -> None:
        wf = self.to_merchant_gate()
        wf.reply("نعم")
        wf.ingest_merchant(merchant_obs())
        m1 = next(p for p in wf.proposals if p.merchant)
        r = wf.reply(f"موافق على {m1.id}")
        self.assertEqual(r.state, "EXECUTING")
        tok = wf.authorize(m1.id, WriteTarget(page_url="https://merchants.google.com/mc/products", resource_id="555")).data["authorization"]["token"]
        self.assertTrue(tok)


class PauseResume(WorkflowTestBase):
    def test_auth_pause_and_resume_same_point(self) -> None:
        wf = self.started()
        r = wf.pause("auth_required", "gtm")
        self.assertEqual(r.state, "AUTH_REQUIRED")
        self.assertIn("لا ترسل كلمة المرور أو رمز التحقق", r.text)
        r = wf.resume()
        self.assertEqual(r.state, "DISCOVERING")

    def test_multiple_accounts_asks_user(self) -> None:
        wf = self.started()
        r = wf.pause("multiple_accounts", "google_ads", accounts="A (123), B (456)")
        self.assertEqual(r.state, "USER_ACTION_REQUIRED")
        self.assertIn("لن أخمّن الحساب الصحيح", r.text)

    def test_fail_safe_revokes_authorizations(self) -> None:
        wf = self.started(issue_obs())
        ga = next(p for p in wf.proposals if p.service == "ga4")
        wf.reply(f"موافق على {ga.id}")
        tok = wf.authorize(ga.id, self.ga4_target()).data["authorization"]["token"]
        r = wf.fail_safe("واجهة غير متوقعة")
        self.assertEqual(r.state, "FAILED_SAFE")
        with self.assertRaises(IllegalTransition):
            wf.record_change(tok, {"captured": True}, "x", "applied")


class SessionPrivacy(WorkflowTestBase):
    def test_no_credentials_persisted(self) -> None:
        wf = self.started()
        o = issue_obs()
        o.d["requests"].append({"url": "https://store.example.com/login?password=hunter2&otp=904512", "step": "home",
                                "headers": {"Cookie": "session=abc"}, "post_data": "token=SECRET123"})
        o.d["cookies"] = [{"name": "sid", "value": "zzz"}]
        wf.ingest_audit(o.build())
        blob = "".join(p.read_text(encoding="utf-8") for p in Path(self.tmp.name).rglob("*.json"))
        for secret in ("hunter2", "904512", "SECRET123", "session=abc", "zzz"):
            self.assertFalse(secret in blob, f"secret {secret!r} persisted")
        sess = Path(self.tmp.name) / "sessions" / f"{wf.id}.json"
        self.assertEqual(oct(sess.stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
