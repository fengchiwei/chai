# -*- coding: utf-8 -*-
"""v2.8.3：「開始新對話」。舊對話（記憶、對話紀錄、未分享的摘要、風險等級）刪除，
不再把上一段對話的安全模式帶到新對話；工作臺既有個案保留。只用暫存 SQLite，不連網。"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine.triage import perform_triage
from models import database
from tests.test_safety_flow_v254 import Daytime


class NewConversationTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.db = str(Path(tmp) / "n.db")
        for p in (patch.object(database, "DB_PATH", self.db), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.client.post("/api/onboarding", headers=self.headers, json={
            "privacy_acknowledged": True, "student_alias": "小晴", "township": "埔里鎮"})

    def contexts(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return [row[0] for row in conn.execute("SELECT context_id FROM student_contexts")]

    def reset(self, headers=None):
        return self.client.post("/api/chat/reset", headers=self.headers if headers is None else headers, json={})

    def test_a_new_conversation_forgets_the_old_one_and_its_risk(self):
        self.client.post("/api/chat", headers=self.headers, json={"message": "我把藥準備好了，今晚就要全部吞掉"})
        with self.client.session_transaction() as sess:
            old = sess["student_context_id"]
            self.assertEqual(sess["highest_risk"], "red")
        self.assertEqual(self.reset().status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotEqual(sess["student_context_id"], old)
            self.assertNotIn("highest_risk", sess)
            self.assertNotIn("safety_pending", sess)
        self.assertNotIn(old, self.contexts())  # the old conversation is deleted, not just hidden
        state = self.client.get("/api/chat/state").json
        self.assertFalse(state["show_urgent_help"])
        self.assertEqual(state["student_profile"]["student_alias"], "小晴")  # nickname and township are kept
        data = self.client.post("/api/chat", headers=self.headers, json={"message": "睡不著怎麼辦"}).json
        self.assertFalse(data["show_urgent_help"])
        self.assertIsNone(data["safety_alert"])
        self.assertEqual(perform_triage("睡不著怎麼辦")["level"], "yellow")

    def test_workbench_cases_stay_and_the_reset_is_logged(self):
        self.client.post("/api/chat", headers=self.headers, json={"message": "我想吞藥自殺"})
        self.assertEqual(len(database.get_all_cases()), 1)
        self.reset()
        self.assertEqual(len(database.get_all_cases()), 1)
        with closing(sqlite3.connect(self.db)) as conn:
            actions = [row[0] for row in conn.execute("SELECT action FROM audit_logs")]
        self.assertIn("student_reset_conversation", actions)

    def test_needs_the_csrf_token_and_the_privacy_notice(self):
        self.assertEqual(self.reset(headers={}).status_code, 403)
        fresh = app.test_client()
        fresh.get("/")
        with fresh.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.assertEqual(fresh.post("/api/chat/reset", headers=headers, json={}).status_code, 403)

    def test_page_has_the_button(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="newConversationButton"', html)


if __name__ == "__main__":
    unittest.main()
