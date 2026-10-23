# -*- coding: utf-8 -*-
"""v2.8：回覆太直接、會重複學生的話（2026-10-23 實測）。提示詞加入輔導常用的傾聽技巧；
把學生原話搬回來的回覆，時間夠時重寫一次。假 API，不連網。"""
import json
from unittest.mock import Mock, patch

from engine import dialogue_ai
from engine.dialogue_ai import SYSTEM_PROMPT
from engine.dialogue_reply import parroting
from tests.test_ai_only_v259 import Base, single

LOW = "最近心情好低落，做什麼事都提不起勁，覺得很空虛"
ECHO = "聽到你最近心情很低落，連平常做的事也提不起勁，還會覺得空虛，這樣的日子一定不太好過。"
BETTER = "好像連平常喜歡的事都變得沒什麼味道，這陣子應該過得很悶。最近有發生什麼事嗎？"


def plain(text):
    return Mock(status_code=200, json=Mock(return_value={"candidates": [{"content": {"parts": [{"text": text}]}}]}))


class PromptTests(Base):
    def test_prompt_teaches_listening_not_echoing(self):
        for phrase in ("不當鸚鵡", "高層次同理", "多反映、少發問", "要不要聽聽一個小方法", "沒事啦", "肯定要具體"):
            self.assertIn(phrase, SYSTEM_PROMPT)

    def test_echo_detection(self):
        self.assertTrue(parroting(ECHO, LOW))
        self.assertFalse(parroting(BETTER, LOW))
        self.assertFalse(parroting("考試真的很累，先好好休息。", "今天考試好累"))  # short messages are not judged
        self.assertFalse(parroting("「最近心情好低落，做什麼事都提不起勁」這句話很重。", LOW))  # an explicit quote


class RewriteTests(Base):
    def test_an_echo_is_rewritten_once(self):
        result, post, _ = self.turn(LOW, {"side_effect": [single(ECHO), plain(BETTER)]})
        self.assertEqual(result["reply"], BETTER)
        self.assertEqual(post.call_count, 2)
        note = post.call_args_list[1].kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("【改寫】", note)
        self.assertIn(ECHO, note)

    def test_a_rewrite_that_still_echoes_keeps_the_first_reply(self):
        result, post, _ = self.turn(LOW, {"side_effect": [single(ECHO), plain(ECHO + "加油。")]})
        self.assertEqual(result["reply"], ECHO)

    def test_no_rewrite_without_time(self):
        with patch.object(dialogue_ai, "REWRITE_SECONDS", 10 ** 6):
            result, post, _ = self.turn(LOW, {"side_effect": [single(ECHO), plain(BETTER)]})
        self.assertEqual((result["reply"], post.call_count), (ECHO, 1))

    def test_a_good_reply_costs_one_call(self):
        result, post, _ = self.turn(LOW, {"return_value": single(BETTER)})
        self.assertEqual((result["reply"], post.call_count), (BETTER, 1))


class HumorStyleTests(Base):
    def test_humor_style_reaches_the_prompt_and_safety_takes_over(self):
        from engine.dialogue_ai import prepare_dialogue
        from engine.triage import perform_triage
        joke = "數學考 3 分，我真的會謝，直接原地退休"
        _, state = prepare_dialogue(joke, perform_triage(joke), {}, use_model=False, hour=14, reply_style="humor")
        self.assertEqual(state["effective_style"], "humor")
        _, post, _ = self.turn(joke, {"return_value": single("3 分也太有個性了吧，數學這次是在跟你玩躲貓貓嗎？")})
        with patch("engine.dialogue_ai.requests.post", return_value=single("嗯。")) as post:
            from engine.dialogue_ai import generate_youth_response
            generate_youth_response(joke, perform_triage(joke), dialogue_state=state)
        prompt = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("【回覆風格：幽默風趣】", prompt)
        self.assertIn("看不懂的梗就老實問", prompt)
        crisis = "我不想活了"
        _, state = prepare_dialogue(crisis, perform_triage(crisis), {}, use_model=False, hour=14, reply_style="humor")
        self.assertEqual(state["effective_style"], "safety")

    def test_page_offers_the_style(self):
        from app import app
        html = app.test_client().get("/").get_data(as_text=True)
        self.assertIn('data-style="humor"', html)


if __name__ == "__main__":
    import unittest
    unittest.main()
