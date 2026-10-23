# -*- coding: utf-8 -*-
"""v2.5.10：學生修正 AI 的誤解（「我說的是未來3天之後」）時，AI 可以問一個問題弄清楚，
修剪多餘問題也不能只剩一句道歉（2026-10-23 實測對話）。假 API，不連網。"""

from engine.dialogue_ai import SYSTEM_PROMPT, prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import drop_trailing_questions
from engine.triage import perform_triage
from tests.test_ai_only_v259 import Base, single

LIVE = [("最近心情好低落，做什麼事都提不起勁，覺得很空虛",
         "聽到你最近心情很低落，連平常做的事也提不起勁，還會覺得空虛，這樣的日子一定不太好過。可以多跟我說說，這種感覺大概是從什麼時候開始的嗎？"),
        ("大概是3天之後", "3天之後才開始有這樣的感覺，你還記得那段時間前後發生了什麼事嗎？就算只是一點點印象也可以說。")]
CORRECTION = "我說的是未來3天之後"
REPAIR = "抱歉，我剛才誤會了你的意思。三天後是有什麼事要發生嗎？"


def earlier_turns():
    state = {}
    for message, reply in LIVE:
        _, state = prepare_dialogue(message, perform_triage(message), state, use_model=False, hour=14)
        state = remember_turn(state, message, reply)
    return state


class RepairTests(Base):
    def test_correction_after_two_questions_may_ask_once(self):
        _, state = prepare_dialogue(CORRECTION, perform_triage(CORRECTION), earlier_turns(), use_model=False, hour=14)
        self.assertEqual(state["current_goal"], "repair_understanding")
        self.assertEqual(state["max_questions"], 1)  # the rest after two questioning turns does not apply

    def test_the_clarifying_question_is_sent_whole(self):
        result, _, _ = self.turn(CORRECTION, {"return_value": single(REPAIR)}, earlier_turns())
        self.assertEqual(result["reply"], REPAIR)

    def test_trimming_never_leaves_a_bare_apology(self):
        self.assertIsNone(drop_trailing_questions(REPAIR))
        good = "考試前一天睡不好很正常，先把明天要帶的東西準備好，今晚早點躺下就好。"
        self.assertEqual(drop_trailing_questions(good + "你覺得呢？"), good)

    def test_other_ways_of_correcting(self):
        for message in ("不是啦，我是說下週的比賽", "我的意思是我不想去", "我是說我朋友不是我", "你搞錯了，是我媽"):
            with self.subTest(message=message):
                _, state = prepare_dialogue(message, perform_triage(message), earlier_turns(), use_model=False, hour=14)
                self.assertEqual(state["current_goal"], "repair_understanding")
        _, state = prepare_dialogue("我說話很小聲，常常沒人聽到", perform_triage("我說話很小聲，常常沒人聽到"),
                                    earlier_turns(), use_model=False, hour=14)
        self.assertNotEqual(state["current_goal"], "repair_understanding")

    def test_prompt_tells_the_model_to_check_ambiguous_answers(self):
        self.assertIn("current_goal=repair_understanding", SYSTEM_PROMPT)
        self.assertIn("兩種讀法", SYSTEM_PROMPT)

    def test_safety_still_comes_first(self):
        message = "我說的是我不想活了"
        _, state = prepare_dialogue(message, perform_triage(message), earlier_turns(), use_model=False, hour=14)
        self.assertEqual(state["current_goal"], "safety_support")


if __name__ == "__main__":
    import unittest
    unittest.main()
