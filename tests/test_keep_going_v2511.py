# -*- coding: utf-8 -*-
"""v2.5.11：不要把天聊死。可以問一個問題的回合，修剪多餘問題時保留第一個問題，
提示詞也要 AI 用好回答的問題把話接下去（2026-10-23 實測：「一段時間了」→ 只回一句感想）。假 API，不連網。"""
from engine.dialogue_ai import SYSTEM_PROMPT, prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import drop_trailing_questions
from engine.triage import perform_triage
from tests.test_ai_only_v259 import Base, single

FIRST = ("最近心情好低落，做什麼事都提不起勁，覺得很空虛",
         "聽你這樣說，最近好像很多事都提不起勁，心裡還有點空空的。這種感覺持續多久了呢？")
SHORT = "一段時間了"
REFLECTION = "嗯，一段時間了，那這份低落可能已經陪你走了一陣子。"
ASK = "這段時間有發生什麼事嗎？"


def earlier_turns():
    _, state = prepare_dialogue(FIRST[0], perform_triage(FIRST[0]), {}, use_model=False, hour=14)
    return remember_turn(state, *FIRST)


class KeepGoingTests(Base):
    def test_trimming_keeps_the_one_allowed_question(self):
        self.assertEqual(drop_trailing_questions(REFLECTION + ASK + "還是你也說不上來？", keep=1), REFLECTION + ASK)
        self.assertEqual(drop_trailing_questions(REFLECTION + ASK), REFLECTION)  # no question allowed: all cut

    def test_reply_to_a_short_answer_still_asks_something(self):
        _, state = prepare_dialogue(SHORT, perform_triage(SHORT), earlier_turns(), use_model=False, hour=14)
        self.assertEqual(state["max_questions"], 1)
        result, _, _ = self.turn(SHORT, {"return_value": single(REFLECTION + ASK + "還是你也說不上來？")}, earlier_turns())
        self.assertEqual(result["reply"], REFLECTION + ASK)
        self.assertIn("Gemini", result["model_used"])

    def test_prompt_asks_for_an_easy_question_instead_of_a_dead_end(self):
        self.assertIn("不要只回一句感想就停", SYSTEM_PROMPT)
        self.assertIn("給兩三個方向讓他挑", SYSTEM_PROMPT)


if __name__ == "__main__":
    import unittest
    unittest.main()
