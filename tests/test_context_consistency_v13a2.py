# -*- coding: utf-8 -*-
"""v1.3-A.2 情境一致性：開心就回應開心、不補上未提及的壓力。虛構句子，不連網。"""
import unittest
from unittest.mock import patch

from engine.dialogue_ai import generate_youth_response, get_auto_warm_response, prepare_dialogue
from engine.dialogue_policy import remember_turn
from engine.dialogue_reply import local_reply, response_violations
from engine.triage import perform_triage

BADMINTON = "爸爸今天要帶我去打我最喜歡的羽球，我很期待！"


def decision(message, previous=None):
    triage = perform_triage(message, previous_level=(previous or {}).get("risk_level", "green"))
    return prepare_dialogue(message, triage, previous, use_model=False)


class ContextConsistencyTests(unittest.TestCase):
    def test_good_news_gets_matching_local_reply(self):
        for message in ("今天真的很開心", BADMINTON, "段考考得不錯，我好高興"):
            with self.subTest(message=message):
                reply = get_auto_warm_response(message)
                for word in ("不好受", "壓力", "緊繃", "喘息", "掛心", "怎麼看自己"):
                    self.assertNotIn(word, reply)
                self.assertLessEqual(reply.count("？"), 1)

    def test_badminton_is_green_and_not_abuse(self):
        triage, state = decision(BADMINTON)
        self.assertEqual(triage["level"], "green")
        self.assertFalse(state["safety_check_required"])
        self.assertIn("羽球", local_reply(BADMINTON, state))

    def test_model_reply_adding_strain_to_good_news_is_flagged_but_sent(self):
        # v2.5.9: a style slip is logged, not replaced by canned text (only serious problems block a reply).
        triage, state = decision(BADMINTON)
        bad = "能和爸爸一起打球，或許是你喘息的空間，也能放下最近的緊繃感。"
        self.assertIn("invented_distress", response_violations(bad, state, BADMINTON))
        good = "要和爸爸去打最喜歡的羽球，難怪你這麼期待！"
        self.assertNotIn("invented_distress", response_violations(good, state, BADMINTON))
        with patch("engine.dialogue_ai._call_model", return_value=({"reply": bad, "model_used": "stub"}, "ok")):
            out = generate_youth_response(BADMINTON, triage, dialogue_state=state)
        self.assertEqual(out["model_used"], "stub")

    def test_student_named_stress_is_not_flagged(self):
        message = "段考壓力很大，但今天打球很開心"
        _, state = decision(message)
        self.assertNotIn("invented_distress", response_violations("段考的壓力還在，不過打球讓你開心了一下。", state, message))

    def test_followup_after_good_news_does_not_dig_for_yearning(self):
        _, state = decision(BADMINTON)
        state = remember_turn(state, BADMINTON, local_reply(BADMINTON, state))
        _, state = decision("上次我還贏了他一局", state)
        reply = local_reply("上次我還贏了他一局", state)
        self.assertNotIn("最重要的是什麼", reply)
        self.assertNotIn("怎麼看自己", reply)

    def test_negated_happiness_is_not_reflected_as_happy(self):
        reply = get_auto_warm_response("我今天沒有很開心")
        self.assertIn("沒有很開心", reply)
        self.assertNotIn("好心情", reply)

    def test_offline_reply_keeps_key_words_and_contrast(self):
        reply = get_auto_warm_response("下週段考好多還沒讀，有點心慌但還讀得進去。")
        self.assertIn("段考", reply)
        self.assertIn("心慌", reply)
        self.assertIn("還讀得進去", reply)
        self.assertNotIn("你說「", reply)


if __name__ == "__main__":
    unittest.main()
