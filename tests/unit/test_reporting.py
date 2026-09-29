"""Arabic templates, reports and the false-success guard (spec §34-36, §45, §54.5)."""

from __future__ import annotations

import re
import unittest

from core.approval.proposals import ACTIONS
from core.audit.engine import run_audit
from core.models import ServiceStatus
from core.reporting.arabic_report import render_audit_report, render_proposals
from core.reporting.guard import FalseSuccessError, check_text, violations
from core.reporting.html_report import render_html
from core.reporting.messages import catalog, placeholders, t
from tests.fixtures.builders import Obs, full_ga4, healthy_funnel

ARABIC = re.compile(r"[؀-ۿ]")


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if not k.startswith("_"):
                yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, str):
        yield path, node


class TemplateTests(unittest.TestCase):
    def test_all_user_messages_are_arabic(self) -> None:
        for path, text in walk(catalog()):
            prose = re.sub(r"\{[a-z_]+\}", "", text)
            if not re.search(r"[^\W\d_]", prose):
                continue  # pure layout template such as "{id}. {service}: {description}"
            with self.subTest(path=path):
                self.assertRegex(text, ARABIC, f"{path} has no Arabic text")

    def test_templates_contain_no_false_success(self) -> None:
        for path, text in walk(catalog()):
            with self.subTest(path=path):
                self.assertEqual(violations(text), [], path)

    def test_every_status_and_action_has_a_message(self) -> None:
        for st in ServiceStatus:
            self.assertTrue(t(f"status.{st.value}"))
        for aid in ACTIONS:
            self.assertTrue(t(f"actions.{aid}"), aid)

    def test_every_finding_code_in_code_has_a_message(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        found = set()
        for p in list((root / "validators").rglob("*.py")) + [root / "core/audit/duplicates.py"]:
            src = p.read_text(encoding="utf-8")
            found |= set(re.findall(r'self\.add\(\s*"([a-z0-9_]+)"', src))
            found |= set(re.findall(r'Finding\("(?:cross_platform|merchant)",\s*"([a-z0-9_]+)"', src))
            found |= set(re.findall(r'"cross_platform",\s*"([a-z0-9_]+)"', src))
        found |= {"issue_" + c for c in ("price_mismatch", "availability_mismatch", "landing_page", "identifiers", "shipping", "policy", "other")}
        found -= {"issue_"}
        missing = {c for c in found if c not in catalog()["findings"] and not c.startswith("dashboard_")}
        self.assertEqual(missing, set())

    def test_placeholders_render(self) -> None:
        self.assertIn("https://x.sa", t("audit_starting", store_url="https://x.sa"))
        with self.assertRaises(KeyError):
            t("audit_starting")
        self.assertEqual(placeholders("{a} و {b}"), {"a", "b"})

    def test_required_phrases_present(self) -> None:
        self.assertIn("🔒 يبدأ مدقق نطاق بالفحص فقط، ولا يجري أي تعديل أو ربط دون موافقتك.", t("welcome"))
        self.assertIn("لا ترسل كلمة المرور أو رمز التحقق داخل المحادثة", t("auth_required", service="GTM"))
        self.assertIn("لن أجري أي تعديل على Merchant Center دون موافقة مستقلة", t("merchant.intro"))
        self.assertEqual(t("report.no_problems_scoped"), "لم تظهر مشاكل ضمن الفحوصات التي تمكنا من تنفيذها.")


class GuardTests(unittest.TestCase):
    def test_forbidden_phrases(self) -> None:
        for bad in ("تم الربط بنجاح", "لا توجد مشاكل", "تم الإصلاح.", "كل شيء يعمل", "موثوقية 100%"):
            with self.subTest(bad=bad), self.assertRaises(FalseSuccessError):
                check_text(f"النتيجة: {bad}")

    def test_scoped_phrases_allowed(self) -> None:
        check_text("لم تظهر مشاكل ضمن الفحوصات التي تمكنا من تنفيذها.")
        check_text("✓ تم التحقق من الربط ضمن الاختبارات التي تم تنفيذها.")
        check_text("تم الإصلاح المقترح وسيتم التحقق منه")  # not a bare claim


class ReportTests(unittest.TestCase):
    def test_clean_audit_uses_scoped_wording(self) -> None:
        o = healthy_funnel()
        full_ga4(o)
        o.meta("PageView", "home").meta("ViewContent", "view_item", content_ids=["S"], content_type="product")
        o.meta("AddToCart", "add_to_cart", value=1, currency="SAR", content_ids=["S"], content_type="product")
        text = render_audit_report(run_audit(o.build(), ["ga4", "meta"]))
        self.assertIn("لم تظهر مشاكل ضمن الفحوصات التي تمكنا من تنفيذها.", text)
        self.assertIn("لم يتم إجراء أي تعديل أثناء الفحص.", text)
        self.assertIn("لم يتم اختبار حدث الشراء", text)
        self.assertIn("🟢 مربوط وتم التحقق من عمله", text)

    def test_static_audit_warns_and_never_verified(self) -> None:
        o = Obs(behavioral=False).page("home", "<script src='https://www.googletagmanager.com/gtag/js?id=G-ABC1234567'></script>")
        text = render_audit_report(run_audit(o.build()))
        self.assertIn("وجود معرّف في الكود لا يعني أن الربط يعمل", text)
        self.assertNotIn("🟢 مربوط وتم التحقق من عمله", text)
        self.assertIn("🔵 تم رصد معرّف فقط", text)

    def test_report_distinguishes_fact_and_inference(self) -> None:
        o = full_ga4(healthy_funnel()).ga4_pageview("home", tid="G-OTHER99999").ga4("view_item", "view_item", currency="USD")
        text = render_audit_report(run_audit(o.build(), ["ga4"]))
        self.assertIn("ملاحظة مؤكدة", text)
        self.assertIn("استنتاج", text)

    def test_proposals_render_and_ask(self) -> None:
        from core.approval.proposals import build_proposals

        a = run_audit(healthy_funnel().build(), ["ga4"])
        props = build_proposals(a)
        text = render_proposals(props)
        self.assertIn("لم يتم إجراء أي تعديل.", text)
        self.assertIn("هل توافق على بدء الربط؟", text)

    def test_html_report(self) -> None:
        html = render_html(render_audit_report(run_audit(healthy_funnel().build(), ["ga4"])))
        self.assertIn("dir='rtl'", html)
        self.assertIn("@font-face{font-family:Tajawal", html)
        self.assertIn("غير مربوط", html)


if __name__ == "__main__":
    unittest.main()
