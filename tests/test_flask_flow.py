"""核心整合檢查：本機測試，不呼叫外部模型或傳送任何通知。"""
import os
import tempfile
import unittest

_test_db = tempfile.NamedTemporaryFile(prefix="anla-test-", suffix=".db", delete=False)
_test_db.close()
os.environ["DATABASE_PATH"] = _test_db.name
os.environ["WORKBENCH_PASSWORD"] = "local-test-password-long-enough"
os.environ["LLM_PROVIDER"] = "builtin"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

from config import Config  # noqa: E402

# unittest 可能先載入其他模組，不能依賴環境變數在 Config 首次 import 前才設定。
Config.DATABASE_PATH = _test_db.name
Config.WORKBENCH_PASSWORD = os.environ["WORKBENCH_PASSWORD"]
Config.LLM_PROVIDER = "builtin"
Config.OPENAI_API_KEY = ""
Config.GEMINI_API_KEY = ""

from app import app  # noqa: E402


class FlowTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        os.unlink(_test_db.name)

    def setUp(self):
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.token = sess["csrf_token"]
        self.headers = {"X-CSRF-Token": self.token}

    def login(self, client=None):
        client = client or self.client
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        response = client.post("/login", data={"password": os.environ["WORKBENCH_PASSWORD"], "csrf_token": token})
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as sess:
            return sess["csrf_token"]

    def onboard(self):
        response = self.client.post("/api/onboarding", headers=self.headers, json={
            "student_email": "student@example.edu.tw", "student_alias": "同學", "township": "南投市",
            "privacy_acknowledged": True,
        })
        self.assertEqual(response.status_code, 200)
        return {"student_email": "student@example.edu.tw"}

    def share_current_summary(self):
        steps = self.client.get("/api/chat/state").json["next_steps"]
        response = self.client.post("/api/referral/consent", headers=self.headers, json={
            "consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"],
        })
        self.assertEqual(response.status_code, 200)
        return response.json

    def test_protected_backend_and_readonly_demo(self):
        self.assertEqual(self.client.get("/api/cases").status_code, 401)
        self.assertEqual(self.client.get("/api/config/llm").status_code, 401)
        self.assertEqual(self.client.get("/counselor").status_code, 302)
        self.assertEqual(self.client.get("/demo").status_code, 302)
        self.assertEqual(self.client.get("/resources").status_code, 200)
        self.login()
        self.assertEqual(self.client.get("/counselor").status_code, 200)
        self.assertEqual(self.client.get("/demo").status_code, 200)
        initial_count = self.client.get("/api/cases").json["count"]
        self.assertEqual(self.client.get("/api/demo/evaluate/CASE-R01").status_code, 200)
        self.assertEqual(self.client.get("/api/cases").json["count"], initial_count)
        self.assertEqual(self.client.get("/api/config/llm").json["temperature"], Config.LLM_TEMPERATURE)

    def test_onboarding_and_student_payload(self):
        self.assertEqual(self.client.post("/api/chat", headers=self.headers, json={"message": "你好"}).status_code, 403)
        denied = self.client.post("/api/onboarding", headers=self.headers, json={
            "student_email": "student@example.edu.tw", "privacy_acknowledged": False,
        })
        self.assertEqual(denied.status_code, 400)
        identity = self.onboard()
        response = self.client.post("/api/chat", headers=self.headers, json={
            **identity, "message": "最近壓力大到想傷害自己，但還沒有計畫"
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["show_support_help"])
        self.assertNotIn("triage", response.json)
        self.assertNotIn("bsrs_details", response.json)
        self.assertNotIn("student_email", response.json)
        urgent = self.client.post("/api/chat", headers=self.headers, json={
            **identity, "message": "我已經把工具準備好，今晚等家人睡著就行動"
        })
        self.assertTrue(urgent.json["show_urgent_help"])
        self.assertIn("119", urgent.json["reply"])
        followup = self.client.post("/api/chat", headers=self.headers, json={**identity, "message": "我還在"})
        self.assertTrue(followup.json["show_urgent_help"])
        staff = app.test_client()
        self.login(staff)
        self.share_current_summary()
        cases = staff.get("/api/cases").json["cases"]
        self.assertTrue(any(c["risk_level"] == "red" for c in cases))
        self.assertTrue(any(c["bsrs5"] == {} for c in cases))

    def test_bsrs_and_manual_contact(self):
        identity = self.onboard()
        incomplete = self.client.post("/api/assessment", headers=self.headers, json={**identity, "bsrs5": {"sleep": 1}})
        self.assertEqual(incomplete.status_code, 400)
        score = {"sleep": 1, "anxiety": 1, "anger": 0, "depression": 1, "inferiority": 0, "suicide": 1}
        response = self.client.post("/api/assessment", headers=self.headers, json={**identity, "bsrs5": score})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("triage", response.json)
        staff = app.test_client()
        csrf = self.login(staff)
        case_id = self.share_current_summary()["case_id"]
        blocked = staff.post(f"/api/cases/{case_id}/status", headers={"X-CSRF-Token": csrf},
            json={"status": "contacted", "contact_confirmed": False, "notes": ""})
        self.assertEqual(blocked.status_code, 400)
        confirmed = staff.post(f"/api/cases/{case_id}/status", headers={"X-CSRF-Token": csrf},
            json={"status": "contacted", "contact_confirmed": True, "notes": "測試：已於系統外完成聯繫"})
        self.assertEqual(confirmed.status_code, 200)

    def test_csrf_and_client_email_cannot_change_server_identity(self):
        identity = self.onboard()
        self.assertEqual(self.client.post("/api/chat", json={**identity, "message": "嗨"}).status_code, 403)
        response = self.client.post("/api/chat", headers=self.headers, json={
            "student_email": "someone-else@example.edu.tw", "message": "嗨"
        })
        # Anonymous entry uses the session identity; a posted email is ignored.
        self.assertEqual(response.status_code, 200)
        profile = self.client.get('/api/chat/state').json['student_profile']
        self.assertEqual(profile['student_email'], 'student@example.edu.tw')

    def test_same_browser_admin_login_preserves_student_crisis(self):
        identity = self.onboard()
        first = self.client.post("/api/chat", headers=self.headers, json={
            **identity, "message": "我已經把工具準備好，今晚等家人睡著就行動"
        })
        self.assertTrue(first.json["show_urgent_help"])
        self.assertTrue(self.client.get("/api/chat/state").json["show_urgent_help"])
        self.onboard()  # 同一信箱重新登錄不會清除危機提示。
        self.assertTrue(self.client.get("/api/chat/state").json["show_urgent_help"])
        self.login()
        followup = self.client.post("/api/chat", headers=self.headers, json={**identity, "message": "我還在"})
        self.assertEqual(followup.status_code, 200)
        self.assertTrue(followup.json["show_urgent_help"])


if __name__ == "__main__":
    unittest.main()
