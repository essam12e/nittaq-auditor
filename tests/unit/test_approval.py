"""Approval parsing, ledger scope and write-gate tests (spec §16, §43, §50)."""

from __future__ import annotations

import unittest

from core.approval.ledger import ApprovalLedger
from core.approval.parser import AMBIGUOUS, APPROVE, MIXED, REJECT, parse_approval, parse_yes_no
from core.approval.proposals import Proposal
from core.execution.gate import WriteRefused, WriteTarget, authorize_write
from core.state_machine import WorkflowMachine, WorkflowState


def prop(pid: str, service: str, action: str, destructive: bool = False, merchant: bool = False, targets=None) -> Proposal:
    return Proposal(pid, action, service, "repair", destructive, merchant, ["x"], "high", list(targets or []))


OFFER = [
    prop("P1", "ga4", "ga4.fix_event_parameters", targets=["G-ABC1234567"]),
    prop("P2", "google_ads", "google_ads.fix_conversion_parameters", targets=["AW-123456789"]),
    prop("P3", "meta", "meta.fix_duplicate_events", destructive=True, targets=["1234567890"]),
    prop("P4", "tiktok", "tiktok.connect"),
]


class ParserTests(unittest.TestCase):
    def test_plain_yes_approves_exactly_the_offer(self) -> None:
        d = parse_approval("نعم", OFFER)
        self.assertEqual(d.kind, APPROVE)
        self.assertEqual(d.approved, ["P1", "P2", "P3", "P4"])
        self.assertEqual(d.needs_destructive_confirmation, ["P3"])

    def test_plain_no_rejects_all(self) -> None:
        d = parse_approval("لا", OFFER)
        self.assertEqual((d.kind, d.rejected), (REJECT, ["P1", "P2", "P3", "P4"]))

    def test_scoped_by_service_name(self) -> None:
        d = parse_approval("موافق على جوجل أناليتكس وميتا", OFFER)
        self.assertEqual(d.approved, ["P1", "P3"])

    def test_scoped_by_ids_with_arabic_digits(self) -> None:
        d = parse_approval("موافق على P١ و P٢", OFFER)
        self.assertEqual(d.approved, ["P1", "P2"])

    def test_mixed_reply(self) -> None:
        d = parse_approval("موافق على GA4 لكن لا تلمس تيك توك", OFFER)
        self.assertEqual((d.kind, d.approved, d.rejected), (MIXED, ["P1"], ["P4"]))

    def test_except_clause(self) -> None:
        d = parse_approval("موافق على الكل ما عدا ميتا", OFFER)
        self.assertEqual(d.approved, ["P1", "P2", "P4"])
        self.assertEqual(d.rejected, ["P3"])

    def test_ambiguous_replies_never_approve(self) -> None:
        for text in ("ربما", "خلني افكر", "نعم؟", "ليش؟", "ok maybe later", "", "   ", "شكرا"):
            with self.subTest(text=text):
                d = parse_approval(text, OFFER)
                self.assertEqual(d.kind, AMBIGUOUS)
                self.assertEqual(d.approved, [])

    def test_group_word_requires_clarification(self) -> None:
        self.assertEqual(parse_approval("جوجل تمام", OFFER).reason, "group_scope")
        self.assertEqual(parse_approval("موافق على البيكسلات", OFFER).reason, "group_scope")

    def test_service_not_in_offer(self) -> None:
        self.assertEqual(parse_approval("موافق على سناب", OFFER).reason, "service_not_in_offer")

    def test_merchant_never_approved_from_tracking_offer(self) -> None:
        self.assertEqual(parse_approval("موافق على ميرشنت", OFFER).reason, "merchant_not_in_offer")

    def test_no_objection_phrase(self) -> None:
        self.assertEqual(parse_approval("لا مانع", OFFER).kind, APPROVE)

    def test_yes_no(self) -> None:
        self.assertEqual(parse_yes_no("نعم ابدأ"), APPROVE)
        self.assertEqual(parse_yes_no("لا"), REJECT)
        self.assertEqual(parse_yes_no("مدري"), AMBIGUOUS)
        self.assertEqual(parse_yes_no("..."), AMBIGUOUS)


class LedgerAndGateTests(unittest.TestCase):
    def executing(self) -> WorkflowMachine:
        m = WorkflowMachine()
        for s in ("DISCOVERING", "AUDITING", "REPORT_READY", "WAITING_FOR_APPROVAL", "EXECUTING"):
            m.transition(WorkflowState(s))
        return m

    def target(self, url: str = "https://analytics.google.com/analytics/web/", rid: str | None = "G-ABC1234567", **kw) -> WriteTarget:
        return WriteTarget(page_url=url, resource_id=rid, **kw)

    def test_approval_for_ga4_does_not_approve_meta(self) -> None:
        led = ApprovalLedger()
        led.approve("P1", "ga4", "ga4.fix_event_parameters")
        self.assertTrue(led.is_approved("P1", "ga4", "ga4.fix_event_parameters"))
        self.assertFalse(led.is_approved("P3", "meta", "meta.fix_duplicate_events"))
        with self.assertRaises(WriteRefused) as cm:
            authorize_write(self.executing(), led, OFFER[2], self.target("https://business.facebook.com/events_manager", "1234567890"))
        self.assertEqual(cm.exception.code, "not_approved")

    def test_approval_for_one_action_does_not_cover_another_on_same_service(self) -> None:
        led = ApprovalLedger()
        led.approve("P1", "ga4", "ga4.fix_event_parameters")
        other = prop("P9", "ga4", "ga4.fix_duplicate_events", targets=["G-ABC1234567"])
        with self.assertRaises(WriteRefused):
            authorize_write(self.executing(), led, other, self.target())

    def test_write_refused_outside_execution_state(self) -> None:
        led = ApprovalLedger()
        led.approve("P1", "ga4", "ga4.fix_event_parameters")
        m = WorkflowMachine()
        m.transition(WorkflowState.DISCOVERING)
        with self.assertRaises(WriteRefused) as cm:
            authorize_write(m, led, OFFER[0], self.target())
        self.assertEqual(cm.exception.code, "not_in_execution_state")

    def test_wrong_account_and_page_protection(self) -> None:
        led = ApprovalLedger()
        led.approve("P1", "ga4", "ga4.fix_event_parameters")
        m = self.executing()
        for tgt, code in (
            (self.target(rid="G-OTHER00000"), "wrong_target"),
            (self.target(rid=None), "target_not_identified"),
            (self.target(url="https://analytics.google.com.evil.io/"), "unexpected_page"),
            (self.target(url="https://tagmanager.google.com/"), "unexpected_page"),
        ):
            with self.subTest(code=code), self.assertRaises(WriteRefused) as cm:
                authorize_write(m, led, OFFER[0], tgt)
            self.assertEqual(cm.exception.code, code)
        self.assertEqual(authorize_write(m, led, OFFER[0], self.target())["proposal"], "P1")

    def test_new_connection_needs_user_confirmed_target(self) -> None:
        led = ApprovalLedger()
        led.approve("P4", "tiktok", "tiktok.connect")
        m = self.executing()
        with self.assertRaises(WriteRefused) as cm:
            authorize_write(m, led, OFFER[3], self.target("https://ads.tiktok.com/i18n/events_manager", "C1"))
        self.assertEqual(cm.exception.code, "target_needs_user_confirmation")
        ok = authorize_write(m, led, OFFER[3], self.target("https://ads.tiktok.com/i18n/events_manager", "C1", user_confirmed_target=True))
        self.assertTrue(ok["token"])

    def test_destructive_needs_separate_confirmation(self) -> None:
        led = ApprovalLedger()
        led.approve("P3", "meta", "meta.fix_duplicate_events")
        m = self.executing()
        tgt = self.target("https://business.facebook.com/events_manager2", "1234567890")
        with self.assertRaises(WriteRefused) as cm:
            authorize_write(m, led, OFFER[2], tgt)
        self.assertEqual(cm.exception.code, "destructive_not_confirmed")
        led.confirm_destructive("P3")
        self.assertTrue(authorize_write(m, led, OFFER[2], tgt)["token"])

    def test_merchant_write_requires_inspection_first(self) -> None:
        led = ApprovalLedger()
        with self.assertRaises(PermissionError):
            led.approve("M1", "merchant", "merchant.fix_price_mismatch")
        led.merchant_inspection = True
        led.approve("M1", "merchant", "merchant.fix_price_mismatch")
        self.assertTrue(led.is_approved("M1", "merchant", "merchant.fix_price_mismatch"))

    def test_google_ads_approval_does_not_approve_merchant(self) -> None:
        led = ApprovalLedger()
        led.approve("P2", "google_ads", "google_ads.fix_conversion_parameters")
        led.merchant_inspection = True
        mprop = prop("M1", "merchant", "merchant.fix_price_mismatch", merchant=True, targets=["555"])
        with self.assertRaises(WriteRefused):
            authorize_write(self.executing(), led, mprop, self.target("https://merchants.google.com/mc/products", "555"))


if __name__ == "__main__":
    unittest.main()
