# -*- coding: utf-8 -*-
"""v2.5.5：模擬測試回饋的 P1／P2 項目（學生端本機回覆、工作臺、資料庫）。虛構句子、不連網。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app, limiter
from config import Config
from engine.ai_agent import generate_counselor_one_page_summary, generate_help_seeking_draft
from engine.dialogue_policy import wants_practical_help
from engine.support import choose_support_offer
from models import database
from tests.test_safety_flow_v254 import Daytime
from tests.test_sim_safety_regressions_v253 import converse

PASSWORD = "local-test-password-long-enough"


class StudentReplyTests(unittest.TestCase):
    def test_direct_questions_are_help_requests(self):
        for message in ("要怎麼跟我媽溝通比較好？", "那數學要怎麼補比較有效？", "可以幫我排一下嗎", "我要怎麼回？",
                        "有沒有什麼具體的方法", "我可以先找我爸幫忙嗎？", "你覺得我要先跟她道歉嗎"):
            with self.subTest(message=message):
                self.assertTrue(wants_practical_help(message))
        for message in ("我不知道", "我不知道怎麼說自己的心情", "我只想先聊一聊，不要給我建議", "我知道怎麼跟他們講了"):
            with self.subTest(message=message):
                self.assertFalse(wants_practical_help(message))

    def test_short_replies_do_not_repeat_the_same_sentence(self):
        results = converse(["嗯", "喔", "是說", "然後", "對啊", "嗯嗯"])
        replies = [r[2] for r in results]
        self.assertLessEqual(sum("這件事我有在聽，不用急著一次說清楚" in r for r in replies), 2)
        for i in range(1, len(replies)):
            asked = [q for q in replies[i].split("。") if q.endswith("？")]
            for q in asked:
                self.assertFalse(any(q in earlier for earlier in replies[max(0, i - 3):i]), q)

    def test_goodbye_gets_a_goodbye(self):
        reply = converse(["今天考試好累", "好 我先去睡了 掰掰"])[1][2]
        self.assertIn("晚安", reply)
        self.assertNotIn("？", reply)

    def test_identity_without_a_role_and_no_model_names(self):
        reply = converse(["你是真人嗎"])[0][2]
        self.assertIn("AI", reply)
        self.assertNotIn("角色設定", reply)
        reply = converse(["你用什麼模型"])[0][2]
        for name in ("Gemini", "Claude", "GPT", "gemini"):
            self.assertNotIn(name, reply)
        self.assertIn("24 小時", converse(["你會記得我嗎"])[0][2])

    def test_privacy_questions_get_answers(self):
        for message, expected in (("你會跟我爸媽講嗎", "不會通知你的家人"), ("這個有錄下來嗎", "24 小時"),
                                  ("可以刪掉我的紀錄嗎", "沒有手動刪除"), ("那我關掉網頁就沒了嗎", "24 小時")):
            with self.subTest(message=message):
                level, state, reply = converse([message])[0]
                self.assertEqual(state["current_goal"], "establish_safety")
                self.assertIn(expected, reply)

    def test_quoted_slur_is_not_good_news(self):
        reply = converse(["上次去參觀，有人說『你們原住民有加分很爽齁』，我超不爽但不知道怎麼回"])[0][2]
        self.assertNotIn("好心情", reply)

    def test_being_left_out_is_not_self_blame(self):
        reply = converse(["我覺得我很沒用", "分組都沒人要跟我"])[1][2]
        self.assertNotIn("責怪都放到自己身上", reply)
        self.assertIn("價值", converse(["我覺得我很爛", "考試又考爛，我真的很爛"])[1][2])

    def test_rational_plan_uses_earlier_turns(self):
        from engine.dialogue_ai import prepare_dialogue
        from engine.dialogue_policy import remember_turn
        from engine.dialogue_reply import local_reply
        from engine.triage import perform_triage
        state = {}
        for message in ("學測只剩一百天了", "我該怎麼規劃？"):
            _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14, reply_style="rational")
            reply = local_reply(message, state)
            state = remember_turn(state, message, reply)
        self.assertIn("學測", reply)
        self.assertIn("一百天", reply)

    def test_cancelling_a_role_keeps_no_questions(self):
        from engine.dialogue_role import resolve_role
        first = resolve_role("請當一位耐心的學長陪我聊，不要一直問我問題")
        after = resolve_role("不用再當學長了", first)
        self.assertEqual(after["companion_role"]["description"], "")
        self.assertTrue(any("問" in p for p in after["companion_role"]["preferences"]))

    def test_no_advice_request_is_remembered(self):
        _, state = choose_support_offer("我只想有人陪我，不要給我建議", "yellow", {}, {"current_goal": "respect_boundary"})
        self.assertTrue(state["declined"])

    def test_counselor_note_has_no_blanks_or_copied_chat(self):
        note = generate_help_seeking_draft({"category": "數學、睡不好", "duration": "尚未提及", "life_impact": "尚未提及"})
        self.assertIn("數學、睡不好", note)
        self.assertNotIn("尚未提及", note)
        self.assertNotIn("【", note)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        self.tmp = tempfile.TemporaryDirectory()
        for p in (patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "w.db")),
                  patch.object(Config, "WORKBENCH_PASSWORD", PASSWORD), patch.object(Config, "LLM_PROVIDER", "builtin"),
                  patch("app.datetime", Daytime)):
            self.enterContext(p)
        database.init_db()

    def tearDown(self):
        limiter.reset()
        self.tmp.cleanup()

    def student_case(self, messages):
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        for message in messages:
            client.post("/api/chat", headers=headers, json={"message": message})
        steps = client.get("/api/chat/state").json["next_steps"]
        client.post("/api/referral/consent", headers=headers,
                    json={"consent": True, "revision": steps["revision"], "consent_kind": steps["consent_kind"]})
        return client, headers

    def staff(self, name="王老師"):
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        client.post("/login", data={"password": PASSWORD, "csrf_token": token, "staff_name": name})
        return client, {"X-CSRF-Token": token}

    def test_notes_are_a_timeline_and_closing_red_needs_a_note(self):
        self.student_case(["我把藥準備好了，今晚就要全部吞掉"])
        staff, headers = self.staff()
        case_id = staff.get("/api/cases").json["cases"][0]["case_id"]
        post = lambda body: staff.post(f"/api/cases/{case_id}/status", headers=headers, json=body)
        self.assertEqual(post({"status": "reviewing", "notes": "02:30 已聯絡生輔組"}).status_code, 200)
        self.assertEqual(post({"status": "completed", "notes": ""}).status_code, 400)
        self.assertEqual(post({"status": "student_shared_summary"}).status_code, 400)  # student-only status
        self.assertEqual(post({"status": "completed", "notes": "家長已帶往就醫"}).status_code, 200)
        notes = staff.get(f"/api/cases/{case_id}").json["case"]["counselor_notes"]
        self.assertIn("02:30 已聯絡生輔組", notes)
        self.assertIn("家長已帶往就醫", notes)
        self.assertIn("王老師", notes)
        self.assertEqual(staff.get("/api/stats").json["red"], 0)  # closed cases are not waiting

    def test_pending_filter_and_reporting_checklist(self):
        self.student_case(["舅舅常常趁家裡沒人的時候摸我身體"])
        staff, _ = self.staff()
        cases = staff.get("/api/cases?status=pending").json["cases"]
        self.assertEqual(len(cases), 1)
        checklist = "".join(staff.get(f"/api/cases/{cases[0]['case_id']}").json["case"]["summary"]["reporting_checklist"])
        self.assertIn("24 小時", checklist)
        self.assertIn("113", checklist)

    def test_risk_rising_after_consent_is_flagged_without_content(self):
        client, headers = self.student_case(["最近每天都睡不著，上課也沒精神"])  # yellow: consent to share is offered
        client.post("/api/chat", headers=headers, json={"message": "我把藥準備好了，今晚就要全部吞掉"})
        staff, _ = self.staff()
        case = staff.get("/api/cases").json["cases"][0]
        self.assertEqual(case["summary"]["raised_after_consent"]["level"], "red")
        self.assertNotIn("吞掉", case["dialogue_snippet"])  # the new message itself was not shared

    def test_security_headers_and_busy_database(self):
        page = app.test_client().get("/")
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.assertIn("object-src 'none'", page.headers["Content-Security-Policy"])
        client, headers = app.test_client(), None
        client.get("/")
        with client.session_transaction() as sess:
            headers = {"X-CSRF-Token": sess["csrf_token"]}
        client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
        with patch("app.process_chat_turn", side_effect=sqlite3.OperationalError("database is locked")):
            busy = client.post("/api/chat", headers=headers, json={"message": "嗨"})
        self.assertEqual(busy.status_code, 503)
        self.assertIn("119", busy.json["error"])

    def test_database_uses_wal(self):
        conn = database.get_connection()
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        finally:
            conn.close()

    def test_peer_bullying_checklist(self):
        summary = generate_counselor_one_page_summary({}, {"level": "orange", "dialogue_safety": {
            "risk_type": "abuse", "risk_types": ["abuse"], "risk_cue": "peer", "risk_signal": "direct"}})
        self.assertIn("霸凌", "".join(summary["reporting_checklist"]))


if __name__ == "__main__":
    unittest.main()
