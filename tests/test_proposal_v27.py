# -*- coding: utf-8 -*-
"""v2.7：補齊與計畫書的落差——學生端 BSRS-5 自填檢核、橙紅自動送出必要安全資訊、
個人帳號與兩種角色、去識別化統計、不提供用藥建議。只用暫存 SQLite，不連網。"""
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine.dialogue_ai import HARD_ISSUES, SYSTEM_PROMPT
from engine.dialogue_policy import build_state
from engine.dialogue_reply import PRIVACY_LIMIT, response_violations
from engine.referral import AUTO_ALERT_ALIAS
from engine.triage import perform_triage
from models import database
from tests.test_safety_flow_v254 import Daytime

CALM = {"sleep": 1, "anxiety": 1, "anger": 0, "depression": 1, "inferiority": 0, "suicide": 0}
WORRYING = {"sleep": 3, "anxiety": 2, "anger": 2, "depression": 3, "inferiority": 2, "suicide": 2}


class Base(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.db = str(Path(tmp) / "t.db")
        for p in (patch.object(database, "DB_PATH", self.db), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch.object(Config, "WORKBENCH_PASSWORD", "builtin-pass-123"), patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()
        self.client = app.test_client()

    def student(self, **profile):
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.client.post("/api/onboarding", headers=self.headers, json={
            "privacy_acknowledged": True, "student_alias": "小晴", "student_email": "q@example.edu.tw",
            "township": "埔里鎮", **profile})

    def assess(self, answers, **extra):
        return self.client.post("/api/assessment", headers=self.headers, json={
            "bsrs5": answers, "duration": "超過 1 個月", "life_impact": "有一點", "support_system": "好像沒有",
            "category": "課業或考試", "elapsed_seconds": 95, **extra})

    def chat(self, message):
        return self.client.post("/api/chat", headers=self.headers, json={"message": message}).json

    def login(self, username="", password="builtin-pass-123", client=None):
        client = client or self.client
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        return client.post("/login", data={"username": username, "password": password, "csrf_token": token,
                                           "staff_name": "測試"})


class SelfCheckTests(Base):
    def test_student_page_offers_the_three_minute_check(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="checkinDialog"', html)
        self.assertIn("data-open-checkin", html)
        self.assertIn("js/checkin.js", html)

    def test_result_is_plain_words_without_lights_or_scores(self):
        self.student()
        data = self.assess(CALM).json
        text = data["result"]["text"]
        for word in ("綠", "黃", "橙", "紅", "分", "BSRS"):
            self.assertNotIn(word, text)
        self.assertIsNone(data["safety_alert"])
        self.assertEqual(database.get_all_cases(), [])  # low risk: nothing reaches the workbench without consent

    def test_worrying_answers_send_the_necessary_safety_information(self):
        self.student()
        data = self.assess(WORRYING).json
        self.assertTrue(data["safety_alert"])
        self.assertTrue(data["result"]["ask_safety"])
        [case] = database.get_all_cases()
        self.assertEqual(case["risk_level"], "orange")
        self.assertEqual(case["status"], "auto_safety_alert")
        self.assertEqual(case["student_alias"], AUTO_ALERT_ALIAS)
        self.assertEqual(case["student_email"], "")
        self.assertEqual(case["bsrs5"], WORRYING)
        self.assertEqual(case["summary"]["checkin_seconds"], 95)
        self.assertNotIn("transcript", case["summary"])

    def test_incomplete_answers_are_refused(self):
        self.student()
        self.assertEqual(self.assess({"sleep": 1}).status_code, 400)


class SafetyHandoffTests(Base):
    def test_red_sends_only_the_sentence_that_raised_it(self):
        self.student()
        self.chat("今天數學考很爛，我們班都在抱怨")
        data = self.chat("我把藥準備好了，今晚就要全部吞掉")
        self.assertIn("必要的安全資訊", data["safety_alert"])
        [case] = database.get_all_cases()
        self.assertEqual(case["risk_level"], "red")
        self.assertIn("今晚就要全部吞掉", case["dialogue_snippet"])
        self.assertNotIn("數學", case["dialogue_snippet"])
        self.assertEqual((case["student_alias"], case["student_email"]), (AUTO_ALERT_ALIAS, ""))
        self.assertEqual(case["summary"]["student_profile"], {"township": "埔里鎮"})
        self.assertIsNone(self.chat("我真的好累")["safety_alert"])  # nothing new to send at the same level
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertTrue(conn.execute("SELECT 1 FROM audit_logs WHERE action='auto_safety_alert'").fetchone())

    def test_later_consent_adds_identity_and_keeps_the_alert_record(self):
        self.student()
        data = self.chat("我想吞藥自殺")
        steps = data["next_steps"]
        response = self.client.post("/api/referral/consent", headers=self.headers, json={
            "consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"]})
        self.assertEqual(response.status_code, 200)
        [case] = database.get_all_cases()
        self.assertEqual(case["student_alias"], "小晴")
        self.assertTrue(case["summary"]["auto_alert"])
        self.assertTrue(case["summary"]["transcript"])

    def test_students_are_told_about_the_exception(self):
        self.assertIn("必要的安全資訊", PRIVACY_LIMIT)
        self.assertIn("自動送出必要的安全資訊", SYSTEM_PROMPT)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("唯一例外", html)


class AccountTests(Base):
    def setUp(self):
        super().setUp()
        database.create_staff_user("lin", "林老師", "counselor", "counselor-pass-1")

    def test_passwords_are_hashed(self):
        with closing(sqlite3.connect(self.db)) as conn:
            stored = conn.execute("SELECT password_hash FROM staff_users WHERE username='lin'").fetchone()[0]
        self.assertNotIn("counselor-pass-1", stored)
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))

    def test_counsellors_see_cases_but_not_admin_tools(self):
        self.assertEqual(self.login("lin", "counselor-pass-1").status_code, 302)
        self.assertEqual(self.client.get("/api/cases").status_code, 200)
        self.assertEqual(self.client.get("/api/stats/breakdown").status_code, 200)
        for url in ("/api/config/llm", "/api/staff/users", "/api/audit"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        page = self.client.get("/counselor").get_data(as_text=True)
        self.assertNotIn('id="modelPanel"', page)
        self.assertIn("林老師（輔導人員）", page)

    def test_admin_manages_accounts_and_the_audit_log_names_people(self):
        self.assertEqual(self.login().status_code, 302)  # blank username = built-in admin
        with self.client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        created = self.client.post("/api/staff/users", headers=headers, json={
            "username": "wang", "display_name": "王老師", "role": "admin", "password": "admin-pass-12"})
        self.assertEqual(created.status_code, 200)
        self.assertNotIn("password", json.dumps(created.json))
        self.assertEqual(self.client.post("/api/staff/users", headers=headers, json={
            "username": "admin", "display_name": "x", "role": "admin", "password": "0123456789"}).status_code, 400)
        self.assertEqual(self.client.post("/api/staff/users", headers=headers, json={
            "username": "chen", "display_name": "陳", "role": "counselor", "password": "short"}).status_code, 400)
        self.client.post("/api/staff/users/lin", headers=headers, json={"active": False})
        other = app.test_client()
        self.assertEqual(self.login("lin", "counselor-pass-1", client=other).status_code, 401)
        actors = [row["actor"] for row in self.client.get("/api/audit").json["logs"]]
        self.assertIn("測試（內建管理員帳號）", actors)
        self.assertTrue(self.client.get("/api/audit").json["chain_ok"])

    def test_people_change_their_own_password(self):
        self.login("lin", "counselor-pass-1")
        with self.client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        self.assertEqual(self.client.post("/api/staff/me/password", headers=headers, json={
            "current_password": "wrong", "new_password": "brand-new-pass"}).status_code, 400)
        self.assertEqual(self.client.post("/api/staff/me/password", headers=headers, json={
            "current_password": "counselor-pass-1", "new_password": "brand-new-pass"}).status_code, 200)
        self.assertTrue(database.authenticate_staff("lin", "brand-new-pass"))

    def test_accounts_work_without_the_shared_password(self):
        with patch.object(Config, "WORKBENCH_PASSWORD", ""):
            self.assertEqual(self.login("lin", "counselor-pass-1").status_code, 302)


class StatsTests(Base):
    def test_breakdown_hides_small_counts_and_identifiers(self):
        self.student()
        self.chat("我想吞藥自殺")
        self.login()
        data = self.client.get("/api/stats/breakdown").json
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("少於 3", text)
        self.assertNotIn("CASE-", text)
        self.assertNotIn("吞藥", text)


class MedicalAdviceTests(unittest.TestCase):
    def test_medication_advice_is_never_sent(self):
        self.assertIn("medical_advice", HARD_ISSUES)
        self.assertIn("不提供藥物", SYSTEM_PROMPT)
        state = build_state("最近都睡不著", perform_triage("最近都睡不著"), {})
        for reply in ("睡不著真的很累，你可以試試吃一顆褪黑激素。", "睡前吃 5 mg 安眠藥就好。", "先自己停藥看看。"):
            self.assertIn("medical_advice", response_violations(reply, state, "最近都睡不著"), reply)
        self.assertNotIn("medical_advice", response_violations(
            "睡不著真的很累。藥物的事可以問醫師或學校護理師。", state, "最近都睡不著"))


if __name__ == "__main__":
    unittest.main()
