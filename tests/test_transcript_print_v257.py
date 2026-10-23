# -*- coding: utf-8 -*-
"""v2.5.7：工作臺看得到完整對話紀錄（到學生同意分享為止），以及乾淨、有稽核紀錄的列印版面。虛構句子、不連網。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine import referral
from engine.referral import get_student_context
from models import database
from tests.test_safety_flow_v254 import Daytime

PASSWORD = "local-test-password-long-enough"


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        self.tmp = tempfile.TemporaryDirectory()
        for p in (patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "t.db")),
                  patch.object(Config, "WORKBENCH_PASSWORD", PASSWORD), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()
        self.student = app.test_client()
        self.student.get("/")
        with self.student.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.student.post("/api/onboarding", headers=self.headers, json={"privacy_acknowledged": True})

    def tearDown(self):
        limiter.reset()
        self.tmp.cleanup()

    def chat(self, message):
        return self.student.post("/api/chat", headers=self.headers, json={"message": message}).json

    def context(self):
        with self.student.session_transaction() as sess:
            return get_student_context(sess["student_context_id"], sess["student_email_hash"])

    def consent(self):
        steps = self.student.get("/api/chat/state").json["next_steps"]
        return self.student.post("/api/referral/consent", headers=self.headers, json={
            "consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"]})

    def staff(self):
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        client.post("/login", data={"password": PASSWORD, "csrf_token": token, "staff_name": "林老師"})
        return client, {"X-CSRF-Token": token}

    def test_every_turn_is_recorded_with_time_and_source(self):
        first = self.chat("今天考試好累")
        self.chat("我不想活了")
        transcript = self.context()["transcript"]
        self.assertEqual([t["role"] for t in transcript], ["user", "assistant", "user", "assistant"])
        self.assertEqual(transcript[0]["text"], "今天考試好累")
        self.assertEqual(transcript[1]["text"], first["reply"])
        self.assertEqual(transcript[3]["source"], "safety")
        self.assertTrue(transcript[0]["at"].startswith("20"))

    def test_consent_text_says_the_whole_conversation_is_shared(self):
        self.chat("我不想活了")
        preview = self.student.get("/api/chat/state").json["next_steps"]["summary_preview"]
        self.assertIn("完整對話紀錄", preview)
        self.assertIn("之後再聊的內容不會自動分享", preview)

    def test_case_has_the_conversation_up_to_consent_only(self):
        self.chat("今天考試好累")
        self.chat("我不想活了")
        self.assertEqual(self.consent().status_code, 200)
        self.chat("其實我剛剛又想到一件事")   # after consent: must not reach the workbench
        staff, _ = self.staff()
        case = staff.get("/api/cases").json["cases"][0]
        case = staff.get(f"/api/cases/{case['case_id']}").json["case"]
        texts = [t["text"] for t in case["summary"]["transcript"]]
        self.assertIn("今天考試好累", texts)
        self.assertIn("我不想活了", texts)
        self.assertNotIn("其實我剛剛又想到一件事", texts)
        self.assertEqual(len(texts), 4)  # both sides of both turns
        self.assertTrue(case["summary"]["student_consent"]["includes_transcript"])

    def test_transcript_is_bounded(self):
        with patch.object(referral, "TRANSCRIPT_LIMIT", 6):
            for i in range(5):
                self.chat(f"第{i}句")
        transcript = self.context()["transcript"]
        self.assertEqual(len(transcript), 6)
        self.assertEqual(transcript[-2]["text"], "第4句")

    def test_printing_is_staff_only_and_audited(self):
        self.chat("我不想活了")
        self.consent()
        staff, headers = self.staff()
        case_id = staff.get("/api/cases").json["cases"][0]["case_id"]
        self.assertEqual(app.test_client().post(f"/api/cases/{case_id}/printed").status_code, 401)
        self.assertEqual(staff.post(f"/api/cases/{case_id}/printed").status_code, 403)  # CSRF
        self.assertEqual(staff.post(f"/api/cases/{case_id}/printed", headers=headers).status_code, 200)
        self.assertEqual(staff.post("/api/cases/CASE-nope/printed", headers=headers).status_code, 404)
        conn = database.get_connection()
        try:
            rows = [(r["actor"], r["action"]) for r in conn.execute("SELECT actor, action FROM audit_logs")]
        finally:
            conn.close()
        self.assertIn(("林老師（內建管理員帳號）", "print_case"), rows)


class PrintStyleTests(unittest.TestCase):
    def test_print_rules_hide_everything_but_the_open_case(self):
        css = Path("static/css/style.css").read_text(encoding="utf-8")
        rules = css[css.index("@media print"):]
        for needle in ("body.case-open > *:not(#summaryModal)", "max-height: none", "overflow: visible", ".no-print",
                       ".print-only"):
            self.assertIn(needle, rules)
        js = Path("static/js/counselor.js").read_text(encoding="utf-8")
        self.assertIn("printCase()", js)
        self.assertNotIn('onclick="window.print()"', js)


if __name__ == "__main__":
    unittest.main()
