# -*- coding: utf-8 -*-
"""v2.5.9：回覆一律由 AI 寫。危險時 AI 依審過的安全文字改寫，沒通過檢查或太慢就用那段固定文字；
AI 無法回覆時，學生看到誠實的說明與求助電話，不再有制式的本機對話回覆。假 API，不連網。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app import app, limiter
from config import Config
from engine import dialogue_ai
from engine.dialogue_ai import (SAFETY_TIMEOUT, UNAVAILABLE_LABEL, generate_youth_response, prepare_dialogue,
                                safety_reply_ok)
from engine.dialogue_reply import safety_reply
from engine.dialogue_role import resolve_role
from engine.triage import perform_triage
from models import database
from tests.test_safety_flow_v254 import Daytime


def single(reply, analysis=None):
    text = json.dumps({"analysis": analysis or {}, "reply": reply}, ensure_ascii=False)
    return Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": text}]}}]}))


class Base(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "LLM_API_KEY", ""), patch.object(Config, "MODEL_AUTO_SELECT", False),
                  patch.object(Config, "LLM_CALL_MODE", "single")):
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def turn(self, message, post, previous=None):
        with patch("engine.dialogue_ai.requests.post", **post) as mock:
            triage, state = prepare_dialogue(message, perform_triage(message), previous, hour=14)
            return generate_youth_response(message, triage, dialogue_state=state), mock, state


class SafetyByAiTests(Base):
    def test_ai_rewrites_the_safety_reply_with_the_hotlines(self):
        rewrite = "聽到你說不想活了，我很在意你。想直接問你：你有想過結束自己的生命嗎？如果已經受傷或正要行動，請現在打 119 或 110；想找人談可以打 1925，二十四小時都有人接。"
        result, post, _ = self.turn("我不想活了", {"return_value": single(rewrite)})
        self.assertEqual(result["reply"], rewrite)
        self.assertIn("Gemini", result["model_used"])
        prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("本輪安全回覆", prompt)
        self.assertIn("1925", prompt)  # the reviewed text is given as reference

    def test_missing_hotline_or_means_question_falls_back_to_the_reviewed_text(self):
        for bad in ("我在這裡陪你，你有想過結束自己的生命嗎？", "你有準備好的工具嗎？請打 119 或 110，也可以打 1925。"):
            with self.subTest(bad=bad):
                dialogue_ai.reset_model_health()
                result, _, state = self.turn("我不想活了", {"return_value": single(bad)})
                self.assertEqual(result["model_used"], "安全回覆")
                self.assertEqual(result["reply"], safety_reply("我不想活了", state))
                self.assertEqual(result["fallback_reason"], "rule_check")

    def test_crisis_turn_waits_at_most_safety_timeout(self):
        result, post, _ = self.turn("我把藥準備好了，今晚就要全部吞掉", {"side_effect": requests.Timeout()})
        self.assertLessEqual(post.call_args.kwargs["timeout"][1], SAFETY_TIMEOUT)
        self.assertIn("119", result["reply"])
        self.assertEqual(result["model_used"], "安全回覆")

    def test_draft_written_before_the_model_raised_risk_is_not_sent(self):
        text = "我想把自己的人生關機，這次不是比喻"
        hints = {"risk": {"signal": "direct", "type": "suicide", "danger": "possible", "subject": "self",
                          "affirmed": True, "evidence": text}}
        result, _, _ = self.turn(text, {"return_value": single("聽起來今天很累，要不要早點休息？", hints)})
        self.assertEqual(result["model_used"], "安全回覆")
        self.assertIn("119", result["reply"])

    def test_check_function(self):
        _, state = prepare_dialogue("我不想活了", perform_triage("我不想活了"), use_model=False, hour=14)
        reference = safety_reply("我不想活了", state)
        self.assertTrue(safety_reply_ok("我很在意你。你有想過結束自己的生命嗎？危險時打 119 或 110，想談談可以打 1925。",
                                        reference, state, "我不想活了"))
        self.assertFalse(safety_reply_ok("我答應你絕對保密。請打 119 或 110，或 1925。", reference, state, "我不想活了"))


class ConversationTests(Base):
    def test_minor_style_slips_are_sent_serious_problems_are_not(self):
        result, _, _ = self.turn("今天考試好累", {"return_value": single("考試真的很累，那你今天有沒有好好吃飯？還有睡飽嗎？")})
        self.assertIn("Gemini", result["model_used"])  # two questions: logged, still the AI's reply
        result, _, _ = self.turn("今天考試好累", {"return_value": single("你其實就是太在意別人的眼光。")})
        self.assertEqual(result["model_used"], UNAVAILABLE_LABEL)
        self.assertIn("1925", result["reply"])

    def test_privacy_question_is_answered_by_the_ai_with_the_facts_as_reference(self):
        answer = "這裡的對話會加密暫存，24 小時沒用就失效；只有你同意分享時老師才看得到，也不會自動通知你家人。"
        result, post, _ = self.turn("你會跟我爸媽講嗎", {"return_value": single(answer)})
        self.assertEqual(result["reply"], answer)
        prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("本輪任務", prompt)
        self.assertIn("24 小時", prompt)

    def test_no_ai_means_an_honest_notice_not_a_canned_reply(self):
        with patch.object(Config, "LLM_PROVIDER", "builtin"):
            triage, state = prepare_dialogue("今天考試好累", perform_triage("今天考試好累"), hour=14)
            result = generate_youth_response("今天考試好累", triage, dialogue_state=state)
            self.assertEqual(result["model_used"], UNAVAILABLE_LABEL)
            self.assertIn("沒有接上 AI", result["reply"])
            self.assertIn("119", result["reply"])
            triage, state = prepare_dialogue("我不想活了", perform_triage("我不想活了"), hour=14)
            result = generate_youth_response("我不想活了", triage, dialogue_state=state)
            self.assertEqual(result["model_used"], "安全回覆")  # the reviewed safety text still answers a crisis

    def test_questions_about_the_ai_never_become_a_role(self):
        for message in ("你是什麼AI模型", "你是哪家的AI", "你是誰做的", "你是AI還是真人", "你是不是機器人"):
            with self.subTest(message=message):
                self.assertEqual(resolve_role(message)["companion_role"]["description"], "")
        self.assertEqual(resolve_role("請當一位耐心的學長陪我聊")["companion_role"]["description"], "一位耐心的學長")


class RouteTests(unittest.TestCase):
    def test_student_sees_unavailable_source_without_a_model(self):
        limiter.reset()
        with tempfile.TemporaryDirectory() as tmp, patch.object(database, "DB_PATH", str(Path(tmp) / "r.db")), \
                patch.object(Config, "LLM_PROVIDER", "builtin"), patch("app.datetime", Daytime):
            database.init_db()
            client = app.test_client()
            client.get("/")
            with client.session_transaction() as sess:
                headers = {"X-CSRF-Token": sess["csrf_token"]}
            client.post("/api/onboarding", headers=headers, json={"privacy_acknowledged": True})
            data = client.post("/api/chat", headers=headers, json={"message": "今天考試好累"}).json
        self.assertEqual(data["reply_source"], "unavailable")
        self.assertEqual(data["fallback_reason"], "builtin")


if __name__ == "__main__":
    unittest.main()
