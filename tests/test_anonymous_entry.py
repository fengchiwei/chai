"""匿名對話、選填資料與既有同意邊界；不連接外部服務。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from config import Config
from models import database


class AnonymousEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(database, "DB_PATH", str(Path(self.temp.name) / "test.db")))
        self.enterContext(patch.object(Config, "LLM_PROVIDER", "builtin"))
        self.enterContext(patch("engine.ai_agent.requests.post", side_effect=AssertionError("No network")))
        database.init_db()
        self.client, self.headers = self.new_client()

    def new_client(self):
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        return client, headers

    def onboard(self, **extra):
        return self.client.post("/api/onboarding", headers=self.headers,
                                json={"privacy_acknowledged": True, **extra})

    def chat(self, message, **extra):
        result = self.client.post("/api/chat", headers=self.headers, json={"message": message, **extra})
        self.assertEqual(result.status_code, 200)
        return result.json

    def consent(self, steps):
        return self.client.post("/api/referral/consent", headers=self.headers, json={
            "consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"]})

    def test_blank_email_school_and_alias_can_chat_refresh_and_assess(self):
        result = self.onboard(student_email="", student_school="", student_alias="")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["student_profile"]["student_alias"], "匿名同學")
        self.chat("今天想找人聊聊段考的事")
        self.client.get("/")
        self.assertEqual(self.client.get("/api/chat/state").json["student_profile"]["student_email"], "")
        self.chat("今天還讀得進去")
        assessment = self.client.post("/api/assessment", headers=self.headers, json={
            "bsrs5": dict.fromkeys(("sleep", "anxiety", "anger", "depression", "inferiority", "suicide"), 0)})
        self.assertEqual(assessment.status_code, 200)
        self.assertEqual(database.get_all_cases(), [])

    def test_empty_email_does_not_join_students_and_request_body_cannot_change_owner(self):
        self.onboard()
        self.chat("我已經把工具準備好，今晚等家人睡著就行動")
        other, headers = self.new_client()
        other.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        first = self.client.get("/api/chat/state").json
        second = other.get("/api/chat/state").json
        self.assertTrue(first["show_urgent_help"])
        self.assertFalse(second["show_urgent_help"])
        with self.client.session_transaction() as one, other.session_transaction() as two:
            self.assertNotEqual(one["student_email_hash"], two["student_email_hash"])
            self.assertNotEqual(one["student_context_id"], two["student_context_id"])
            forged_id = one["student_context_id"]
        result = other.post("/api/chat", headers=headers, json={"message": "今天很開心", "student_email": "other@example.com", "student_context_id": forged_id})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json["show_urgent_help"])
        self.assertNotIn("今天很開心", self.client.get("/api/chat/state").json["next_steps"]["summary_preview"])
        self.assertEqual(database.get_all_cases(), [])

    def test_contact_edits_keep_crisis_and_dialogue_and_invalidate_old_consent(self):
        self.onboard(township="埔里鎮")
        old = self.chat("我已經把工具準備好，今晚等家人睡著就行動")["next_steps"]
        with self.client.session_transaction() as sess:
            original_id = sess["student_context_id"]
        for email in ("help@example.com", ""):
            saved = self.onboard(student_email=email, student_school="測試高中", township="埔里鎮")
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json["show_urgent_help"])
            self.assertIn("工具準備好", saved.json["next_steps"]["summary_preview"])
            with self.client.session_transaction() as sess:
                self.assertEqual(sess["student_context_id"], original_id)
        self.assertEqual(self.consent(old).status_code, 409)
        self.assertEqual(database.get_all_cases(), [])
        fresh = self.client.get("/api/chat/state").json["next_steps"]
        accepted = self.consent(fresh)
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("信箱：未提供", accepted.json["referral_form"])
        self.assertIn("測試高中", accepted.json["referral_form"])
        self.assertFalse(accepted.json["external_referral_sent"])
        self.assertEqual(database.get_all_cases()[0]["student_email"], "")

    def test_optional_email_still_validates_and_privacy_and_csrf_are_required(self):
        for email in (None, 123, [], "not-an-email"):
            self.assertEqual(self.onboard(student_email=email).status_code, 400)
        self.assertEqual(self.onboard(privacy_acknowledged=False).status_code, 400)
        self.assertEqual(self.client.post("/api/onboarding", json={"privacy_acknowledged": True}).status_code, 403)
        self.assertEqual(self.client.post("/api/chat", headers=self.headers, json={"message": "你好"}).status_code, 403)
        self.assertEqual(self.onboard(student_email="private@example.com").status_code, 200)

    def test_existing_email_based_session_is_preserved_when_contact_is_removed(self):
        self.onboard(student_email="old@example.edu.tw")
        self.chat("最近壓力大到想傷害自己，但還沒有計畫")
        with self.client.session_transaction() as sess:
            owner = sess["student_email_hash"]
            context_id = sess["student_context_id"]
        saved = self.onboard()
        self.assertEqual(saved.json["next_steps"]["consent_kind"], "referral")
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["student_email_hash"], owner)
            self.assertEqual(sess["student_context_id"], context_id)
        self.assertIn("傷害自己", saved.json["next_steps"]["summary_preview"])


if __name__ == "__main__":
    unittest.main()
