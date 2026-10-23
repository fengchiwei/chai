# -*- coding: utf-8 -*-
"""v2.8.1：「睡不著怎麼辦」被 AI 的分析標成自殺線索，學生被問「有沒有想過結束生命」，也沒拿到睡眠方法
（2026-10-23 實測）。AI 的風險線索若只引用日常困擾字詞，系統不採用。假 API，不連網。"""
from engine.dialogue_policy import everyday_distress_only
from tests.test_ai_only_v259 import Base, single

SLEEP = "睡不著怎麼辦"
OVERCALLED = {"risk": {"signal": "direct", "type": "suicide", "danger": "possible", "subject": "self",
                       "affirmed": True, "evidence": "睡不著"}}
HELP = "睡不著真的很磨人。可以試試睡前一小時把手機放到房間外，讓腦袋慢慢關機；要不要聽聽其他小方法？"


class FalseAlarmTests(Base):
    def test_everyday_distress_quoted_as_suicide_is_ignored(self):
        result, _, state = self.turn(SLEEP, {"return_value": single(HELP, OVERCALLED)})
        self.assertFalse(state["safety_check_required"])
        self.assertEqual(state["risk_level"], "yellow")
        self.assertEqual(state["current_goal"], "support_choice")
        self.assertEqual(result["reply"], HELP)
        self.assertNotIn("結束自己的生命", result["reply"])

    def test_new_risk_wording_from_the_model_still_counts(self):
        text = "我想把自己的人生關機，這次不是比喻"
        hint = {"risk": {**OVERCALLED["risk"], "evidence": text}}
        _, _, state = self.turn(text, {"return_value": single("聽到了。", hint)})
        self.assertTrue(state["safety_check_required"])

    def test_the_filter(self):
        for quote in ("睡不著", "最近好累壓力好大", "心情不好", "考試好焦慮"):
            self.assertTrue(everyday_distress_only(quote), quote)
        for quote in ("好累好想消失", "活著好累", "不想活", "我想把自己的人生關機", "想傷害自己"):
            self.assertFalse(everyday_distress_only(quote), quote)


if __name__ == "__main__":
    import unittest
    unittest.main()
