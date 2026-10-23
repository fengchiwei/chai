# -*- coding: utf-8 -*-
"""v2.9：決賽前補強——南投官方資源查詢、公開示範模式、管理員每輪診斷、.env.example。
只用暫存 SQLite 與假 API，不連網。"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import TURN_DIAGNOSTICS, app, limiter
from config import Config
from engine import knowledge
from engine.dialogue_ai import prepare_dialogue
from engine.triage import perform_triage
from models import database
from tests.test_ai_only_v259 import Base, single
from tests.test_safety_flow_v254 import Daytime

ROOT = Path(__file__).resolve().parents[1]


class LocalResourceTests(Base):
    def state(self, message, township="南投市"):
        return prepare_dialogue(message, perform_triage(message), {}, use_model=False, hour=14, township=township)[1]

    def test_where_to_go_questions_get_verified_local_entries(self):
        cards = knowledge.select("我住埔里，附近有衛生所嗎", self.state("我住埔里，附近有衛生所嗎"))
        self.assertEqual(cards[0]["title"], "埔里鎮衛生所")
        self.assertIn("電話：049-2982157", cards[0]["steps"])
        self.assertTrue(cards[0]["sources"][0]["url"].startswith("https://"))
        nearby = knowledge.select("哪裡可以諮商？", self.state("哪裡可以諮商？", township="竹山鎮"))
        self.assertIn("竹山區社區心理衛生中心", [c["title"] for c in nearby][0])

    def test_unrelated_questions_get_no_local_entries(self):
        for message in ("睡不著怎麼辦", "今天放學想去打球"):
            self.assertFalse([c for c in knowledge.select(message, self.state(message)) if c["id"].startswith("resource-")])

    def test_the_reply_cites_the_resource_and_links_its_source(self):
        reply = "埔里可以先找埔里鎮衛生所，電話 049-2982157。（資料來源：南投縣政府）"
        result, post, _ = self.turn("我住埔里，附近有衛生所嗎", {"return_value": single(reply)})
        prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("049-2982157", prompt)
        self.assertIn("電話、地址照卡片原樣寫", prompt)
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["sources"][0]["url"], "https://data.gov.tw/dataset/168126")


class MaskingTests(unittest.TestCase):
    def test_student_identifiers_stay_masked_but_official_numbers_do_not(self):
        from engine.dialogue_ai import _scrub_prompt
        prompt = ("記憶：我的手機是 0912345678，住在南投市中興路 100 號\n\n"
                  + knowledge.REFERENCE_HEADER + "】卡1｜埔里鎮衛生所｜電話：049-2982157｜地址：南投縣埔里鎮中正路1號"
                  + "\n\n【輸出格式】我的手機是 0912345678")
        scrubbed = _scrub_prompt(prompt)
        self.assertNotIn("0912345678", scrubbed)
        self.assertIn("049-2982157", scrubbed)
        self.assertIn("南投縣埔里鎮中正路1號", scrubbed)


class RouteBase(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        TURN_DIAGNOSTICS.clear()
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for p in (patch.object(database, "DB_PATH", str(tmp / "f.db")), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch.object(Config, "WORKBENCH_PASSWORD", "builtin-pass-123"), patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()

    def student(self):
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        return client, headers

    def admin(self):
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        client.post("/login", data={"password": "builtin-pass-123", "csrf_token": token})
        return client


class DemoModeTests(RouteBase):
    def test_a_public_demo_never_writes_formal_cases(self):
        with patch.object(Config, "PUBLIC_DEMO_MODE", True):
            client, headers = self.student()
            self.assertIn("公開示範網站", client.get("/").get_data(as_text=True))
            data = client.post("/api/chat", headers=headers, json={"message": "我想吞藥自殺"}).json
            self.assertTrue(data["show_support_help"])          # the safety reply and help still come
            self.assertIsNone(data["safety_alert"])               # but no automatic alert is written
            steps = data["next_steps"]
            response = client.post("/api/referral/consent", headers=headers, json={
                "consent": True, "revision": steps["revision"], "consent_kind": "request"})
            self.assertEqual(response.status_code, 403)
            self.assertIn("1925", response.json["error"])
        self.assertEqual(database.get_all_cases(), [])

    def test_off_by_default(self):
        self.assertFalse(Config.PUBLIC_DEMO_MODE)
        self.assertNotIn("公開示範網站", self.student()[0].get("/").get_data(as_text=True))


class DiagnosticsTests(RouteBase):
    def test_admins_see_per_turn_diagnostics_without_content(self):
        client, headers = self.student()
        client.post("/api/chat", headers=headers, json={"message": "我的秘密是我喜歡隔壁班的人"})
        turns = self.admin().get("/api/admin/diagnostics").json["turns"]
        self.assertEqual(len(turns), 1)
        for key in ("request_id", "model_used", "response_origin", "fallback_reason", "latency_ms", "risk_level"):
            self.assertIn(key, turns[0])
        self.assertNotIn("隔壁班", json.dumps(turns, ensure_ascii=False))
        self.assertEqual(client.get("/api/admin/diagnostics").status_code, 401)


class EnvExampleTests(unittest.TestCase):
    def test_every_setting_is_listed_and_no_real_key_is_included(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        read = set()
        for path in [ROOT / "config.py", *(ROOT / "engine").glob("*.py")]:
            read |= set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', path.read_text(encoding="utf-8")))
        missing = {name for name in read - {"RENDER_EXTERNAL_URL"} if name not in example}
        self.assertEqual(missing, set())
        self.assertIsNone(re.search(r"(?:AIza|sk-|AQ\.|gsk_|xai-)[\w-]{8,}", example))


if __name__ == "__main__":
    unittest.main()
