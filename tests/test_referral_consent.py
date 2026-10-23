"""同意邊界、身分沿用與四級選項；只用暫存 SQLite，不呼叫外部服務。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, TOWNSHIPS, referral_resources
from config import Config
from models import database


class ReferralConsentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = patch.object(database, "DB_PATH", str(Path(self.temp.name) / "test.db"))
        self.database.start()
        self.provider = patch.object(Config, "LLM_PROVIDER", "builtin")
        self.provider.start()
        self.network = patch("engine.ai_agent.requests.post", side_effect=AssertionError("No external request"))
        self.network.start()
        database.init_db()
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.profile = {"student_email": "student@example.edu.tw", "student_alias": "小安",
                        "student_school": "測試高中", "township": "仁愛鄉", "privacy_acknowledged": True}
        self.assertEqual(self.client.post("/api/onboarding", headers=self.headers, json=self.profile).status_code, 200)

    def tearDown(self):
        self.network.stop()
        self.provider.stop()
        self.database.stop()
        self.temp.cleanup()

    def chat(self, message):
        result = self.client.post("/api/chat", headers=self.headers, json={
            "student_email": self.profile["student_email"], "message": message,
        })
        self.assertEqual(result.status_code, 200)
        return result.json

    def yellow(self):
        result = self.client.post("/api/assessment", headers=self.headers, json={
            "student_email": self.profile["student_email"],
            "dialogue_snippet": "最近睡不好，上課很累，想跟老師聊聊。",
            "bsrs5": {"sleep": 2, "anxiety": 2, "anger": 1, "depression": 2, "inferiority": 1, "suicide": 0},
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["next_steps"]["consent_kind"], "summary")
        return result.json

    def consent_body(self, **extra):
        steps = self.client.get("/api/chat/state").json["next_steps"]
        return {"consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"], **extra}

    def consent(self, **extra):
        return self.client.post("/api/referral/consent", headers=self.headers, json=self.consent_body(**extra))

    def test_green_never_enters_workbench_or_gets_referral_form(self):
        result = self.chat("今天放學後想去打球。")
        self.assertEqual([c["action"] for c in result["next_steps"]["choices"]], ["continue", "school", "resources"])
        self.assertIsNone(result["next_steps"]["summary_preview"])
        self.assertNotIn("referral_form", result)
        forged = self.consent(consent_kind="referral")
        self.assertEqual(forged.status_code, 409)
        self.assertEqual(database.get_all_cases(), [])
        self.assertNotIn("risk_level", json.dumps(result))

    def test_green_assessment_does_not_save_a_completed_case(self):
        result = self.client.post("/api/assessment", headers=self.headers, json={
            "student_email": self.profile["student_email"],
            "bsrs5": dict.fromkeys(("sleep", "anxiety", "anger", "depression", "inferiority", "suicide"), 0),
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(database.get_all_cases(), [])

    def test_yellow_note_does_not_share_until_explicit_consent(self):
        self.yellow()
        note = self.client.post("/api/generate-draft", headers=self.headers, json={
            "target": "輔導老師", "case_info": {"category": "不應被採用的偽造內容"},
        })
        self.assertEqual(note.status_code, 200)
        # v2.5.5: a topic word from the student's own messages, not their sentences copied in.
        self.assertIn("睡不好", note.json["draft"])
        self.assertNotIn("尚未提及", note.json["draft"])
        self.assertNotIn("偽造內容", note.json["draft"])
        self.assertEqual(database.get_all_cases(), [])
        self.assertEqual(self.consent(consent=False).status_code, 200)
        self.assertEqual(database.get_all_cases(), [])
        response = self.consent()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("referral_form", response.json)
        case = database.get_all_cases()[0]
        self.assertEqual(case["status"], "student_shared_summary")
        self.assertEqual(case["summary"]["student_consent"]["kind"], "summary")

    def test_orange_A_only_creates_referral_and_reuses_profile(self):
        result = self.chat("最近壓力大到想傷害自己，但還沒有計畫")
        self.assertEqual(result["next_steps"]["consent_kind"], "referral")
        self.assertFalse(result["show_urgent_help"])
        self.assertEqual(database.get_all_cases(), [])
        declined = self.consent(consent=False)
        self.assertNotIn("referral_form", declined.json)
        self.assertEqual(database.get_all_cases(), [])
        accepted = self.consent(preferred_name="阿安")
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("阿安", accepted.json["referral_form"])
        self.assertIn("測試高中", accepted.json["referral_form"])
        self.assertFalse(accepted.json["notification_connected"])
        self.assertFalse(accepted.json["external_referral_sent"])
        case = database.get_all_cases()[0]
        self.assertEqual(case["status"], "student_requested_referral")
        self.assertEqual(case["student_email"], self.profile["student_email"])
        self.assertEqual(case["township"], "仁愛鄉")
        self.assertEqual(case["summary"]["student_profile"]["student_school"], "測試高中")

    def test_repeated_consent_does_not_duplicate_or_reset_staff_status(self):
        self.chat("最近壓力大到想傷害自己，但還沒有計畫")
        first = self.consent(preferred_name="").json
        database.update_case_status(first["case_id"], "reviewing", "已開始覆核")
        second = self.consent().json
        self.assertEqual(first["case_id"], second["case_id"])
        self.assertEqual(len(database.get_all_cases()), 1)
        case = database.get_all_cases()[0]
        self.assertEqual(case["student_alias"], "小安")
        self.assertEqual(case["status"], "reviewing")
        self.assertEqual(case["summary"]["student_consent"]["kind"], "referral")
        self.chat("我還想多說幾句")
        self.assertEqual(database.get_case_by_id(first["case_id"])["dialogue_snippet"], case["dialogue_snippet"])

    def test_red_keeps_phones_after_decline_consent_and_refresh(self):
        result = self.chat("我已經把工具準備好，今晚等家人睡著就行動")
        self.assertTrue(result["show_urgent_help"])
        self.assertEqual(database.get_all_cases(), [])
        self.consent(consent=False)
        self.consent()
        self.assertTrue(self.client.get("/api/chat/state").json["show_urgent_help"])
        self.assertTrue(self.chat("我還在")["show_urgent_help"])
        html = self.client.get("/").text
        panel = html.split('id="urgentHelpPanel"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("hidden", panel.split(">", 1)[0])
        for phone in ("119", "110", "1925"):
            self.assertIn(f'href="tel:{phone}"', panel)

    def test_stale_yellow_consent_cannot_become_referral_silently(self):
        self.yellow()
        old = self.consent_body()
        self.chat("我已經把工具準備好，今晚等家人睡著就行動")
        response = self.client.post("/api/referral/consent", headers=self.headers, json=old)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json["show_urgent_help"])
        self.assertEqual(database.get_all_cases(), [])

    def test_csrf_strict_boolean_and_session_identity(self):
        self.yellow()
        self.assertEqual(self.client.post("/api/referral/consent", json=self.consent_body()).status_code, 403)
        for value in ("false", "true", 0, 1, None):
            self.assertEqual(self.consent(consent=value).status_code, 400)
        for key, value in (("student_email", "other@example.edu.tw"), ("township", "南投市"), ("risk_level", "red"), ("case_id", "other")):
            self.assertEqual(self.consent(**{key: value}).status_code, 400)
        for name in (None, ["名字"], "a" * 31, "名字\n偽造欄位"):
            self.assertEqual(self.consent(preferred_name=name).status_code, 400)
        other = app.test_client()
        other.get("/")
        with other.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.assertEqual(other.post("/api/referral/consent", headers=headers, json=self.consent_body()).status_code, 403)
        self.assertEqual(database.get_all_cases(), [])

    def test_all_townships_have_one_local_center_student_center_and_1925(self):
        for township in TOWNSHIPS:
            contacts = referral_resources(township)
            self.assertEqual(len(contacts), 3, township)
            self.assertIn("1925", [c["phone"] for c in contacts])
            self.assertIn("049-2222549#317", [c["phone"] for c in contacts])
            self.assertTrue(all(c["phone_href"].startswith("tel:") and c["source_url"].startswith("https://") for c in contacts))
        self.assertIn("049-2911925", [c["phone"] for c in referral_resources("仁愛鄉")])
        self.assertIn("049-2631925", [c["phone"] for c in referral_resources("水里鄉")])
        self.assertIn("049-2202662", [c["phone"] for c in referral_resources("草屯鎮")])


if __name__ == "__main__":
    unittest.main()
