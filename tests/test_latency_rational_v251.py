# -*- coding: utf-8 -*-
"""v2.5.1：降低模型「思考」時間以縮短等待；理性風格的範例、三段結構檢查與多餘問句修剪。虛構句子、假 API，不連網。"""
import json
import unittest
from unittest.mock import Mock, patch

from config import Config
from engine import dialogue_ai, model_router
from engine.dialogue_ai import STYLE_INSTRUCTIONS, _call_model, _thinking_config, generate_youth_response, prepare_dialogue
from engine.dialogue_reply import drop_trailing_questions, response_violations
from engine.triage import perform_triage

PLAN = "下週段考三科，我不知道該怎麼規劃讀書時間"
GOOD = ("1. 重點整理：下週要考三科，你想把讀書時間排出來。\n2. 目前卡點：範圍很多，不確定先讀哪一科。\n"
        "3. 下一步：今晚先列出三科剩下的範圍，把最沒把握的排在明天第一段；要不要這樣做由你決定。")


def gemini(text):
    return Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": text}]}}]}))


def payload(call):
    return call.kwargs["json"]["generationConfig"]


class ThinkingTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "MODEL_AUTO_SELECT", False), patch.object(Config, "GEMINI_THINKING", "low")):
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def test_each_model_family_gets_its_lowest_thinking_setting(self):
        self.assertEqual(_thinking_config("gemini-2.5-flash"), {"thinkingBudget": 0})
        self.assertEqual(_thinking_config("gemini-2.5-flash-lite"), {"thinkingBudget": 0})
        self.assertEqual(_thinking_config("gemini-2.5-pro"), {"thinkingBudget": 128})  # Pro cannot turn it off
        self.assertEqual(_thinking_config("gemini-3.5-flash-lite"), {"thinkingLevel": "low"})
        self.assertEqual(_thinking_config("gemini-3-pro-preview"), {"thinkingLevel": "low"})
        self.assertIsNone(_thinking_config("gemini-flash-latest"))  # unknown generation: leave it alone
        with patch.object(Config, "GEMINI_THINKING", "default"):
            self.assertIsNone(_thinking_config("gemini-3.5-flash"))

    def test_setting_reaches_the_request(self):
        with patch.object(Config, "GEMINI_MODEL", "gemini-3.5-flash"), \
             patch("engine.dialogue_ai.requests.post", return_value=gemini("我在，慢慢說。")) as post:
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "ok")
        self.assertEqual(payload(post.call_args)["thinkingConfig"], {"thinkingLevel": "low"})

    def test_model_that_rejects_the_setting_is_retried_once_without_it(self):
        rejected = Mock(status_code=400, text='{"error": {"message": "Invalid JSON payload: Unknown name \\"thinkingLevel\\""}}')
        with patch.object(Config, "GEMINI_MODEL", "gemini-3.5-flash"), \
             patch("engine.dialogue_ai.requests.post", side_effect=[rejected, gemini("我在。")]) as post:
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual(status, "ok")
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("thinkingConfig", payload(post.call_args))
        with patch.object(Config, "GEMINI_MODEL", "gemini-3.5-flash"), \
             patch("engine.dialogue_ai.requests.post", return_value=gemini("我在。")) as post:
            self.assertEqual(model_router.candidates("gemini"), ["gemini-3.5-flash"])  # not paused
            _call_model("系統提示", "今天好累", [])
        self.assertEqual(post.call_count, 1)  # remembered: no second rejection
        self.assertNotIn("thinkingConfig", payload(post.call_args))

    def test_other_bad_requests_are_not_retried(self):
        with patch.object(Config, "GEMINI_MODEL", "gemini-3.5-flash"), \
             patch("engine.dialogue_ai.requests.post", return_value=Mock(status_code=400, text="Request contains an invalid argument.")) as post:
            _, status = _call_model("系統提示", "今天好累", [])
        self.assertEqual((status, post.call_count), ("rejected", 1))


class RationalStyleTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "MODEL_AUTO_SELECT", False), patch.object(Config, "LLM_CALL_MODE", "single")):
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def reply_for(self, model_reply, message=PLAN):
        triage = perform_triage(message)
        with patch("engine.dialogue_ai.requests.post",
                   return_value=gemini(json.dumps({"analysis": {}, "reply": model_reply}, ensure_ascii=False))):
            triage, state = prepare_dialogue(message, triage, reply_style="rational")
            return state, generate_youth_response(message, triage, dialogue_state=state)

    def test_instruction_carries_a_worked_example(self):
        example = STYLE_INSTRUCTIONS["rational"].split("→\n", 1)[1]
        self.assertIn("1. 重點整理", example)
        self.assertNotRegex(example, r"[？?]")

    def test_good_three_line_reply_is_used(self):
        state, result = self.reply_for(GOOD)
        self.assertEqual(state["current_goal"], "support_choice")
        self.assertEqual(result["reply"], GOOD)
        self.assertNotIn("fallback_reason", result)

    def test_plan_request_without_the_three_lines_is_rejected(self):
        state, _ = self.reply_for(GOOD)
        self.assertIn("rational_structure", response_violations("可以先列出三科的範圍，再挑最沒把握的開始。", state, PLAN))
        _, result = self.reply_for("可以先列出三科的範圍，再挑最沒把握的開始。")
        self.assertEqual(result["fallback_reason"], "rule_check")
        self.assertIn("3. 下一步", result["reply"])  # local three-line plan instead

    def test_extra_question_at_the_end_is_trimmed_instead_of_discarding_the_reply(self):
        _, result = self.reply_for(GOOD + "你覺得這樣可行嗎？")
        self.assertEqual(result["reply"], GOOD)
        self.assertIn("Gemini", result["model_used"])

    def test_a_next_step_written_as_a_question_is_not_salvaged(self):
        reply = GOOD.split("3. 下一步")[0] + "3. 下一步：要不要今晚先列出三科剩下的範圍？"
        self.assertIsNone(drop_trailing_questions("你想怎麼做？"))
        _, result = self.reply_for(reply)
        self.assertEqual(result["fallback_reason"], "rule_check")

    def test_casual_chat_in_rational_style_does_not_need_the_three_lines(self):
        state, _ = self.reply_for("今天天氣很好。", message="今天天氣很好")
        self.assertNotIn("rational_structure", response_violations("天氣好，出門走走也不錯。", state, "今天天氣很好"))


if __name__ == "__main__":
    unittest.main()
