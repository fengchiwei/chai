# -*- coding: utf-8 -*-
"""v2.8.5：隨時看得到的「找真人幫忙」。綠色、黃色時學生也能自己選擇分享摘要、請人聯絡；
橙紅色時沿用原本的轉介。只用暫存 SQLite，不連網。"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from models import database
from tests.test_safety_flow_v254 import Daytime


class HelpRequestTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        for p in (patch.object(database, "DB_PATH", str(Path(tmp) / "h.db")),
                  patch.object(Config, "LLM_PROVIDER", "builtin"), patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}

    def onboard(self, email=""):
        self.client.post("/api/onboarding", headers=self.headers, json={
            "privacy_acknowledged": True, "student_alias": "小晴", "township": "埔里鎮", "student_email": email})

    def chat(self, message):
        return self.client.post("/api/chat", headers=self.headers, json={"message": message}).json

    def ask(self, steps, kind="request", **extra):
        return self.client.post("/api/referral/consent", headers=self.headers, json={
            "consent": True, "revision": steps["revision"], "consent_kind": kind, **extra})

    def test_a_green_student_can_ask_for_a_person(self):
        self.onboard("q@example.edu.tw")
        steps = self.chat("今天放學後想去打球")["next_steps"]
        response = self.ask(steps, note="想聊跟家人吵架的事，下課時間聯絡我", preferred_name="晴晴")
        self.assertEqual(response.status_code, 200)
        [case] = database.get_all_cases()
        self.assertEqual((case["status"], case["risk_level"]), ("student_requested_help", "green"))
        self.assertEqual(case["student_alias"], "晴晴")
        self.assertEqual(case["student_email"], "q@example.edu.tw")
        consent = case["summary"]["student_consent"]
        self.assertEqual((consent["kind"], consent["note"]), ("request", "想聊跟家人吵架的事，下課時間聯絡我"))
        self.assertTrue(case["summary"]["transcript"])

    def test_without_contact_the_student_is_told_nobody_can_reach_them(self):
        self.onboard()
        steps = self.chat("最近考試好累")["next_steps"]
        message = self.ask(steps).json["message"]
        self.assertIn("無法主動聯絡你", message)

    def test_on_an_orange_conversation_the_request_is_the_referral(self):
        self.onboard()
        steps = self.chat("我想吞藥自殺")["next_steps"]
        self.assertEqual(self.ask(steps).status_code, 200)
        [case] = database.get_all_cases()
        self.assertEqual(case["status"], "student_requested_referral")
        self.assertEqual(case["summary"]["student_consent"]["kind"], "referral")

    def test_checks(self):
        self.onboard()
        steps = self.chat("今天放學後想去打球")["next_steps"]
        self.assertEqual(self.ask(steps, kind="referral").status_code, 409)  # cannot forge a referral
        self.assertEqual(self.ask(steps, note="長" * 301).status_code, 400)
        self.assertEqual(self.ask({**steps, "revision": steps["revision"] - 1}).status_code, 409)
        self.assertEqual(database.get_all_cases(), [])

    def test_the_button_is_always_on_the_page(self):
        html = self.client.get("/").get_data(as_text=True)
        button = re.search(r'<button[^>]*id="headerReferralButton"[^>]*>', html).group(0)
        self.assertNotIn("hidden", button)
        self.assertIn("找真人幫忙", html)


if __name__ == "__main__":
    unittest.main()
