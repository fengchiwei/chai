# -*- coding: utf-8 -*-
"""v2.5.2：活潑風格的表面錯誤（「包」代替「吧」、困擾時用 🥰）就地修正，不整則丟棄；
「真的嗎」「為什麼」這類對上一句的反應不再被當成新話題。虛構句子、假 API，不連網。"""
import json
import unittest
from unittest.mock import Mock, patch

from config import Config
from engine import dialogue_ai
from engine.dialogue_ai import STYLE_INSTRUCTIONS, SYSTEM_PROMPT, generate_youth_response, prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import local_reply, response_violations, tidy_surface
from engine.triage import perform_triage

LIVE = "朋友之間有小摩擦，心情多少會受影響包 🥰 那時候發生了什麼事呀？"  # Gemini, 2026-10-23


class SurfaceTests(unittest.TestCase):
    def test_live_gemini_reply_is_repaired(self):
        self.assertEqual(tidy_surface(LIVE, "跟朋友有小摩擦"), "朋友之間有小摩擦，心情多少會受影響吧，那時候發生了什麼事呀？")

    def test_good_news_keeps_its_emoji(self):
        reply = "太讚了吧 🎉 抽到稀有角色超幸運！"
        self.assertEqual(tidy_surface(reply, "我今天抽到超稀有的遊戲角色超開心！"), reply)

    def test_real_words_with_bao_are_untouched(self):
        for reply in ("早餐吃了麵包🍞，有吃東西就好。", "記得帶包～", "過年領紅包🧧的感覺不錯。"):
            with self.subTest(reply=reply):
                self.assertEqual(tidy_surface(reply, "今天普普通通"), reply)

    def test_zhuyin_ba(self):
        self.assertEqual(tidy_surface("先休息一下好ㄅ。", "好累"), "先休息一下好吧。")

    def test_emoji_at_the_end_is_just_removed(self):
        self.assertEqual(tidy_surface("被誤會真的很悶😆", "被同學誤會了"), "被誤會真的很悶")

    def test_lively_instruction_names_both_rules(self):
        self.assertIn("「包」", STYLE_INSTRUCTIONS["lively"])
        self.assertIn("🥰", STYLE_INSTRUCTIONS["lively"])


def converse(messages, style="warm"):
    state = {}
    for message in messages:
        _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, reply_style=style)
        reply = local_reply(message, state)
        last, state = state, remember_turn(state, message, reply)
    return last, reply


class ReactionTests(unittest.TestCase):
    """「真的嗎」「為什麼」right after a reply answer that reply, not a new event (live run, 2026-10-23)."""

    def test_doubt_is_answered_not_turned_into_a_feeling_question(self):
        state, reply = converse(["跟朋友有小摩擦", "真的嗎？"], style="lively")
        self.assertEqual((state["current_goal"], state["reaction"]), ("respond_to_reaction", "doubt"))
        self.assertNotIn("失望", reply)
        self.assertNotIn("這件事我有在聽", reply)
        self.assertEqual(response_violations(reply, state, "真的嗎？"), [])

    def test_asking_back_gets_an_explanation(self):
        for message in ("為什麼", "什麼意思", "怎麼說～"):
            with self.subTest(message=message):
                state, reply = converse(["今天考試考砸了", message])
                self.assertEqual(state["reaction"], "ask")
                self.assertIn("說得太快", reply)
                self.assertIn("continue_drilling", state["forbidden_actions"])
                self.assertIsNone(state.get("support_offer"))

    def test_not_a_reaction(self):
        self.assertEqual(converse(["真的嗎"])[0]["reaction"], "")  # nothing to react to yet
        for message in ("真的很難過", "為什麼大家都不理我", "是喔我也不知道"):
            with self.subTest(message=message):
                self.assertEqual(converse(["我考砸了", message])[0]["reaction"], "")

    def test_model_is_told_what_the_goal_means(self):
        self.assertIn("current_goal=respond_to_reaction", SYSTEM_PROMPT)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        dialogue_ai.reset_model_health()
        for p in (patch.object(Config, "LLM_PROVIDER", "gemini"), patch.object(Config, "GEMINI_API_KEY", "test-key"),
                  patch.object(Config, "MODEL_AUTO_SELECT", False), patch.object(Config, "LLM_CALL_MODE", "single")):
            self.enterContext(p)

    def tearDown(self):
        dialogue_ai.reset_model_health()

    def test_repaired_ai_reply_is_sent_instead_of_a_local_fallback(self):
        message = "跟朋友有小摩擦"
        text = json.dumps({"analysis": {}, "reply": LIVE}, ensure_ascii=False)
        response = Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": text}]}}]}))
        with patch("engine.dialogue_ai.requests.post", return_value=response):
            triage, state = prepare_dialogue(message, perform_triage(message), reply_style="lively")
            result = generate_youth_response(message, triage, dialogue_state=state)
        self.assertNotIn("包", result["reply"])
        self.assertNotIn("🥰", result["reply"])
        self.assertIn("Gemini", result["model_used"])


if __name__ == "__main__":
    unittest.main()
